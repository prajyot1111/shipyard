"""The serve role: the deck's HTTP door. Stdlib `http.server`, bound to 127.0.0.1.

    GET  /, /console[/queue|/shipped|/journal]         the shells (app/), never cached: they carry the cookie
    GET  /ui.js, /ui.css, /manifest.json, /sw.js       the page's files (app/), ETagged and no-cache: kept,
                                                       and asked about on every load (c-540); the deck's
                                                       scripts are app/views.json's, and / and /sw.js are
                                                       filled from it (keel/deckviews.py, c-634)
    GET  /icons/*, /favicon.ico, /console.webmanifest  its icons and Bosun's manifest (app/)
    GET  /api/state[?scope=deck|bosun[&archived=1]  the state document (deckstate), with an
              [&card=<id>]]                             ETag; a matching If-None-Match is a 304.
                                                       A scope is what that page draws, and the
                                                       card it has open (c-540)
    GET  /api/events                                   server-sent events: what changed, as it
                                                       changes, so the page is told rather than
                                                       asking (keel/deckevents.py)
    GET  /api/card/<id>                                one card's events and context, ETagged too
    GET  /api/health                                   the health verdict and the services block, unconditional
    GET  /api/atlas, /api/atlas/<slug>                 the Atlas: its page list, one rendered page
    GET  /api/setup                                    the Setup view: repos, suggestions, packs (keel/onboarding.py)
    GET  /api/settings                                 the Settings view: the schema and every value (keel/settings.py)
    GET  /api/hello                                    whether the user has said hello in Bosun's session (keel/firstrun.py)
    GET  /api/board/<b-id>[?since=<line>]              one board, and the ops after that line
    GET  /api/boards[?q=<words>][&deleted=1]           every board with its card, searched (keel.boardlist); the trash with deleted
    GET  /api/boards/uses?ids=<b-id>,...               the plans and outcomes that embed those boards (keel.boarduses)
    GET  /api/ci/<c-id>                                a card's checks and builds, the CI page's data (keel.ciroute)
    GET  /api/comments/<c-id>                          a card's review rounds, the comments page's data (keel.commentsroute)
    GET  /board[/<b-id>[?view=...]]                    the page again: the board's own route
    POST /api/board/<b-id>/inbox                       one file HE put on the board (keel.boardfiles)
    POST /api/board/<b-id>/ask                         one question for the board's house; a turn id
    GET  /api/board/<b-id>/ask/<turn>                  that turn's answer, once it has one
    GET  /api/house, POST /api/house/{open,say,close}  the kept-alive voice conversations (keel/housetier.py)
    POST /api/action                                   {"verb": ...} through actions; a write drops the cache
    GET  /api/artifact/<token>                         a file under state/cards or segments_dir
    GET  /segments/<name>/app/...                      a segment's own app
    GET  /segments/<name>/{data/<file>,summary.json}   what that app reads (keel.segments)
    GET  /segments/<name>/inbox                        what is waiting in its upload inbox
    POST /segments/<name>/{decisions,inbox}            what that app posts back, same origin only
    any  /voice/...                                    proxied to the voice gateway on voice_port
    WS   /voice/ws                                     spliced to the gateway, byte for byte
    anything else                                      proxied to lavish on lavish_port

A POST that acts as him (`/api/action`, the board's drop box and its ask) needs the page's own proof: the cookie the shell's GET sets,
and a browser's same-origin word (`keel/deckauth.py`). Anything else is a 403.

The whole `/segments/` prefix is the deck's, exactly as the old dashboard claimed it: a
path under it that matches no route here is a 404 rather than a 503 from the lavish proxy.
`keel/segments.py` holds everything about a segment that is not the static app.

The voice tier (`keel/voicetier.py`) is the phone's one door onto the voice gateway.

The lavish proxy streams (its `/events/` is a channel that never ends) with a watch on the
client's own socket, so a browser that walks away from a quiet channel is noticed then
rather than on a write that may never come (`relay`, card c-276). It presents lavish
an Origin it will accept: lavish checks Origin against its own host, which behind a proxy
never matches, so the check moves up one hop. This server compares the browser's claimed
origin against its own Host and, only on a match, hands lavish `http://127.0.0.1:<port>`.

It also starts lavish when a person asks for a surface and nothing answers. Lavish exits
about thirty minutes after the last browser and the last poll disconnect, so a surface left
overnight is not merely unattended, it is not served, and the deck's link to it would be a
connection refused at exactly the hour it is wanted.
"""

import gzip
import hashlib
import http.client
import json
import mimetypes
import os
import posixpath
import re
import resource
import secrets
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from keel import (actions, artifacts, atlas, boardask, boardfiles, boardlist, boards,
                  boardtrash, boarduses, cardfiles,
                  deckauth, deckevents, deckreload, deckstate, deckviews, firstrun, health,
                  lavishlayer, merging, onboarding, restart, segments,
                  settings, voice)
from keel.board import open_board
from keel import config as config_module
from keel.config import Config
from keel.housetalk import SESSIONS
from keel.housetier import HOUSE_PREFIX, HouseTier
from keel.voicetier import VOICE_ROUTE, VoiceTier
from keel.ciroute import CI_API, CiRoute
from keel.commentsroute import COMMENTS_API, CommentsRoute
from keel.planroute import FILE_PAGE, PLAN_API, PLAN_PAGE, PlanRoute, plan_stamp

STARTED_HEAD: str | None = None   # the commit this process started on, set in `serve`
CLIENT_HANGUPS = 0                # replies a client did not stay for; counted, never logged as errors


def descriptors() -> dict:
    """How many descriptors this process holds, and how many it may: `{"open", "soft"}`.

    This door is the only place that can answer for the serve process. `keel doctor` runs
    in its own process, where a count says nothing about this one, so it reads the number
    from here (`keel/doctor.py`). `/dev/fd` is the process's own table on macOS and Linux
    alike. Nulls when the platform will not say, which the doctor reads as "no number".
    """
    try:
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        return {"open": len(os.listdir("/dev/fd")), "soft": soft}
    except OSError:
        return {"open": None, "soft": None}


VOICE_APP_PATH = "/segments/voice/app/"


def voice_url(cfg) -> str:
    """Where the deck opens Voice: its own address when it has one (`[voice] app_url`), so the
    installed Voice app is the one that opens, else the path under the deck."""
    return (cfg.voice_app_url or "") + VOICE_APP_PATH


def with_code_state(cfg, doc: dict) -> dict:
    """`config.code_head`, `config.serve_head` and `config.code_moved`: whether the checkout
    has moved past the commit this process loaded, so the deck can offer Restart. Plus
    `config.descriptors`, which is this process counting its own open files, and `health`,
    Keel's one verdict (`keel/health.py`), rebuilt at most once a minute."""
    doc["health"] = health.current(cfg)
    head = merging.code_head(cfg.root)
    doc.setdefault("config", {}).update({
        "code_head": head, "serve_head": STARTED_HEAD,
        "code_moved": bool(head and STARTED_HEAD and head != STARTED_HEAD),
        "descriptors": descriptors(), "voice_url": voice_url(cfg)})
    return doc


# One setup change at a time (c-618): a clone takes minutes, and two writes of the config
# racing a re-exec would leave the second answered by a process that is going away.
SETUP_LOCK = threading.Lock()
SETUP_BUSY = "another setup change is running; try again when it has finished"


def restart_when_quiet(voice_changed: bool = False) -> None:
    """Exec once nothing this process holds would be cut (`restart.due`: a conversation, a
    house or door call, a deck action), as the drain's restart waits; checked every second. A Settings save
    that changed `[voice]` first reinstalls the voice gateway when it is loaded, in the same
    quiet moment (c-633, decision voice-apply: reload): the gateway reads its environment,
    not the config."""
    while not restart.due("config")[0]:
        time.sleep(1)
    if voice_changed:
        voice.reload_if_loaded()
    restart_process()


# How often the deck looks whether its checkout moved (c-637). A deploy fast-forwards the
# live checkout; the drain execs between passes, and the deck follows within this, so the old
# server never goes on sending the new page (2026-10-04: c-634's page needs the serve that
# fills it, and an old deck sent it unfilled, a blank page, until restarted by hand).
CODE_POLL_SECONDS = 2.0


def follow_code(root: Path, started_on: str | None, head=None, restart_fn=None,
                pause: float = CODE_POLL_SECONDS, sleep=time.sleep) -> None:
    """Exec onto the checkout's new code once it moves past `started_on`, when nothing this
    process holds would be cut (`restart.busy`: a conversation, a house or door call, a deck
    action). A head that cannot be read is unknown, never moved (`merging.code_head`). Runs
    on its own thread for good, and only in a deck with no drain in its process (`run`): the
    drain's own restart, between its passes, is that process's. It reads `restart.busy`, not
    `restart.due`, so the drain's once-per-reason line stays the drain's."""
    head = head or merging.code_head
    restart_fn = restart_fn or restart_process
    while True:
        sleep(pause)
        now = head(root)
        if not (now and started_on and now != started_on):
            continue
        said = ""
        while True:
            reason = restart.busy()
            if not reason:
                break
            if reason != said:
                print(f"keel serve: code moved since start; the restart waits: {reason}",
                      file=sys.stderr, flush=True)
                said = reason
            sleep(1)
        print(f"keel serve: the code moved to {now[:8]}; restarting onto it", file=sys.stderr, flush=True)
        restart_fn()
        return


def config_stamp(cfg) -> tuple | None:
    """The config file as it stands (its change time and size), or None when it cannot be read."""
    try:
        found = Path(cfg.source).stat() if cfg.source else None
    except OSError:
        return None
    return (found.st_mtime_ns, found.st_size) if found else None


def schedule_restart(voice_changed: bool = False) -> None:
    """A config change the deck cannot read in place (`keel/deckreload.py`): exec again once
    quiet, half a second after the answer has gone out."""
    threading.Timer(0.5, restart_when_quiet, kwargs={"voice_changed": voice_changed}).start()


# Which process answered (c-729): `/api/setup` carries it, so a page waiting out a restart
# can tell the new deck from the one it asked before. A re-exec imports this module again.
BOOT = secrets.token_hex(8)


def restart_process() -> None:
    """Exec this process again with the same arguments: the `restart` verb, after the
    response has gone out. Under launchd it is the same as an exit with KeepAlive."""
    os.execv(sys.executable, [sys.executable, *sys.argv])


# What `app/icons/build.py` writes into `app/icons/`, served under `/icons/`.
ICONS = (*(f"{app}-{size}.png" for app in ("keel", "bosun")
           for size in ("192", "512", "maskable-192", "maskable-512", "180", "32")),
         "keel-tile.svg", "keel-maskable.svg", "keel.ico", "bosun-tile.svg", "bosun-maskable.svg",
         "bosun.ico", *(f"{mark}-glyph.svg" for mark in ("keel", "harbor", "voice", "bosun", "bosun-small")))
APP_DIR = Path(__file__).resolve().parent.parent / "app"
APP_FILES = {"/": "index.html", "/index.html": "index.html", "/ui.css": "ui.css",
             "/ui.find.css": "ui.find.css",
             # THE DECK'S SCRIPTS ARE ITS MANIFEST'S (c-634): app/views.json lists them in
             # their load order, and the page, the service worker and this table are all
             # drawn from it (keel/deckviews.py). A file added there is served at once
             # (`Handler.app_path`), and listed here from the next start.
             **deckviews.served(APP_DIR),
             # The plan page (`keel/planroute.py`): its renderer, its static diagram (the
             # board's own drawing, laid out once), and its styles.
             "/ui.plan.js": "ui.plan.js", "/ui.plandiagram.js": "ui.plandiagram.js",
             "/ui.planblocks.js": "ui.planblocks.js", "/ui.plan.css": "ui.plan.css",
             "/ui.planpage.js": "ui.planpage.js", "/ui.planlook.js": "ui.planlook.js",
             "/ui.ci.js": "ui.ci.js",      # the CI page (c-642), drawn on the plan page's shell
            "/ui.comments.js": "ui.comments.js",   # the review comments page (c-643), the same shell
             # lane FC: code in colour, and a review finding as one card
             "/ui.plancode.js": "ui.plancode.js", "/ui.planfinding.js": "ui.planfinding.js",
             # ELK, vendored (app/vendor/README.md names the version and its licence). The
             # board's diagram is laid out by it, in the browser; nothing here reads it.
             "/vendor/elk.bundled.js": "vendor/elk.bundled.js",
             # highlight.js, vendored the same way (lane FC): ES modules the plan page
             # imports only when it has code to colour (app/ui.plancode.js).
             **{f"/vendor/highlight/{name}": f"vendor/highlight/{name}" for name in (
                 "core.min.js", *(f"languages/{lang}.min.js" for lang in
                                  ("xml", "python", "javascript", "sql", "yaml", "json", "bash")))},
             "/manifest.json": "manifest.json", "/sw.js": "sw.js",
             # The icons (c-518): what `app/icons/build.py` derives from the glyphs he picked.
             # Bosun's manifest waits here for the /console page (BO-1), which links it and
             # nothing else has to move.
             "/favicon.ico": "icons/keel.ico", "/console.webmanifest": "console.webmanifest",
             **{f"/icons/{name}": f"icons/{name}" for name in ICONS},
             # The two space themes. A house does not fetch them from here (it links the
             # copy `house.ensure_theme` put beside its surface), but the deck's own origin
             # serves them so a surface opened through Open plan (live) can reach one too.
             "/theme-work.css": "theme-work.css", "/theme-personal.css": "theme-personal.css",
             "/theme-console.css": "theme-console.css",
             # The Console's own script and styles (c-519): only `/console` loads them.
             "/ui.console.js": "ui.console.js", "/ui.console.asks.js": "ui.console.asks.js",
             "/ui.console.css": "ui.console.css",
             # The phone layer the lavish proxy injects into a lavish page, under a prefix
             # lavish claims nothing at (`keel/lavishlayer.py`). The deck's own page never
             # loads these two, so they are not in the service worker's shell list either,
             # for the same reason the two themes are not.
             **lavishlayer.FILES}
CARD_ROUTE = re.compile(r"^/api/card/(c-\d+)$")
EVENTS_ROUTE = "/api/events"
BOARD_ID = re.compile(r"^b-\d+$")
ARTIFACT_ROUTE = re.compile(r"^/api/artifact/([A-Za-z0-9_.=-]+)$")
HEALTH_ROUTE = "/api/health"
SETUP_ROUTE = "/api/setup"
SETTINGS_ROUTE = "/api/settings"
# Meet Bosun's hello watch (c-729): a read, outside the setup lock (r1.F6)
HELLO_ROUTE = "/api/hello"
ATLAS_ROUTE = re.compile(r"^/api/atlas(?:/([\w.-]+))?$")
BOARD_API = re.compile(r"^/api/board/(b-\d+)$")
BOARDS_LIST = "/api/boards"
BOARDS_USES = "/api/boards/uses"
BOARD_INBOX = re.compile(r"^/api/board/(b-\d+)/inbox$")
BOARD_ASK = re.compile(r"^/api/board/(b-\d+)/ask$")
BOARD_ASK_TURN = re.compile(r"^/api/board/(b-\d+)/ask/([0-9a-f]+)$")
# The board is the one route with a PATH of its own: a board is a thing he sends himself a
# link to, and `/board/b-004?view=outline` is that link. WHICH VIEW rides in the query
# rather than the path, because it is a way of looking at one board rather than another
# thing to open. The server answers every shape with the same page and `app/ui.core.js`
# reads both halves. The trailing number is the frames era's deep link, kept in the pattern
# and ignored, so a link he sent himself in September still opens its board.
BOARD_PAGE = re.compile(r"^/board(?:/(b-\d+)(?:/(\d+))?)?/?$")
SEGMENT_APP = re.compile(r"^/segments/([\w.-]+)/app(?:/(.*))?$")
SEGMENT_ROUTE = re.compile(r"^/segments/.*$")   # the whole prefix is ours; see keel/segments.py
# THE SHELL: the one answer that carries the page's cookie (`keel/deckauth.py`). `BOARD_PAGE`
# is the shell too, under the board's own path.
SHELL_PATHS = ("/", "/index.html")
# The plan and outcome pages' own shell (`keel/planroute.py`, P2-5), under PLAN_PAGE and FILE_PAGE.
PLAN_SHELL = "plan.html"
# Bosun's page (c-519): a page of its own, installable apart from the deck with the
# manifest scoped to it (`/console.webmanifest`, c-518). Each of its four sections is a
# route of the one shell (c-591): Now at `/console`, then Queue, Shipped and Journal.
CONSOLE_SECTIONS = ("queue", "shipped", "journal")
CONSOLE_PATHS = ("/console", "/console/") + tuple(f"/console/{name}" for name in CONSOLE_SECTIONS)
CONSOLE_SHELL = "console.html"
# What the proxy carries that a house wrote: lavish's artifact frame
# (`Handler.house_written_headers`).
HOUSE_WRITTEN = ("/artifact/",)
# `.ico` by its IANA name on every machine: macOS's type table says image/x-icon, Linux's
# image/vnd.microsoft.icon, and the deck answers the same everywhere (c-635).
mimetypes.add_type("image/vnd.microsoft.icon", ".ico")
PASS_REQUEST = ("Content-Type", "Accept", "Cache-Control")
# What is relayed from lavish's own answer. The CORS headers are in the list because the
# artifact is rendered in a SANDBOXED iframe with no `allow-same-origin`, so its origin is
# `null` and every asset it fetches from lavish (a whiteboard plan's fonts, above all) is a
# cross origin request. Lavish sends `access-control-allow-origin: *` for exactly that;
# dropping it here meant the fonts failed, lavish's layout gate never lifted, and the plan
# he opened on his phone was "Checking layout. One moment." forever. The deck adds no CORS
# header of its own, it only stops eating the ones lavish sent.
PASS_RESPONSE = {"content-type", "cache-control", "location", "etag", "last-modified", "content-disposition",
                 "access-control-allow-origin", "access-control-allow-headers",
                 "access-control-allow-methods", "access-control-expose-headers", "vary"}
NO_STORE = "no-store, max-age=0"
# THE PAGE'S OWN FILES ARE KEPT AND ASKED ABOUT (c-540). They used to be `NO_STORE`, so
# every switch between Keel and Bosun fetched every script again, ELK's 470 KB among them.
# `no-cache` lets the browser keep a file and makes it ask on every use, so a deploy still
# shows on the very next load and an unchanged file costs a 304 with no body.
REVALIDATE = "no-cache"
# A JSON answer smaller than this goes out as it is: gzip would buy nothing.
GZIP_FLOOR = 1024
# THE DECK'S OWN CEILING ON A REQUEST BODY. Above every legitimate body this server has:
# the biggest is a 10 MB upload into a segment's or a board's inbox, which hold their own
# caps as well (a 16 MB board file carried as base64 by `board.attach`, about 22 MB, was
# bigger until c-622 removed the verb; the ceiling did not move). It is deliberately one number for every route rather than a per-route rule,
# because the routes that needed one already have one and what was missing was the floor
# under all of them (`<install>/history/docs/blackboard.md`, "a cap on the action body").
MAX_BODY = 32 * 1024 * 1024


GZIPPED: dict = {}
# The segment app files worth compressing; an image is already as small as gzip makes it.
SEGMENT_ZIPPED = (".js", ".css", ".json", ".webmanifest", ".svg", ".txt", ".map")


def compressed(path: Path) -> bytes:
    """A page file's gzip, made once per file and mtime; a changed file is compressed again."""
    stamp = path.stat().st_mtime_ns
    held = GZIPPED.get(path)
    if held and held[0] == stamp:
        return held[1]
    body = gzip.compress(path.read_bytes(), compresslevel=6, mtime=0)
    GZIPPED[path] = (stamp, body)
    return body


def file_tag(path: Path, zipped: bool) -> str:
    """An app file's ETag: its mtime and size, and which encoding (a gzipped and a plain
    answer are different bytes, so they must not share a tag). A deploy moves the mtime."""
    stat = path.stat()
    return f'"{stat.st_mtime_ns:x}-{stat.st_size:x}{"-gz" if zipped else ""}"'


def board_lines(cfg, board_id: str) -> int:
    """How many lines that board's `ops.log` holds, or 0 for no board and no file.

    The event stream's own sweep: the size is the cheap half and is all that has to change
    for the count to be worth taking, so a board nobody is pushing to costs one stat.
    """
    if not board_id:
        return 0
    path = boards.board_dir(cfg, board_id) / boards.OPS_FILE
    try:
        if not path.stat().st_size:
            return 0
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


class BodyTooLarge(Exception):
    """A `Content-Length` above `MAX_BODY`. Raised before anything is read, so the body is
    still on the socket and the connection has to end."""


# The origin rules live with the rest of the deck's auth (`keel/deckauth.py`); these names
# stay here because the routes below, and the tiers that subclass this handler, use them.
host_of = deckauth.host_of
same_origin = deckauth.same_origin


LAVISH_BINARY = "lavish-axi"
LAVISH_LOG = Path.home() / ".lavish-axi" / "server.log"
REVIVE_COOLDOWN = 20.0      # a lavish that will not start is not hammered once per request
REVIVE_WAIT = 10.0          # how long a revive waits for the port to answer
STREAM_TICK = 2.0           # how often a relayed answer looks to see its client is still there
SESSION_ROUTE = re.compile(r"^/session/[\w.-]+/?$")

_revive_lock = threading.Lock()
_revive_last = 0.0
_lavish_proc: subprocess.Popen | None = None      # the one this server started, kept, never orphaned


def lavish_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - any failure at all means "not up"
        return False


def by_a_person(method: str, path: str) -> bool:
    """True for the requests a human actually makes: opening a surface, its live channel,
    and answering on it. Everything else this server proxies is a page's own asset, a
    scanner, or a favicon, and starting a server for thirty minutes on behalf of one of
    those is how a dormant lavish gets woken all night by nobody."""
    if method == "GET":
        return SESSION_ROUTE.match(path) is not None or path.startswith("/events/")
    return method == "POST" and path.startswith("/api/")


def lavish_revive(port: int) -> bool:
    """Start the shared lavish server unless it is already up. True when it answers.

    Detached into its own session so it outlives this server, and its Popen is kept with a
    thread waiting on it, so the child is reaped rather than left a zombie of the request
    thread that happened to start it.
    """
    global _revive_last, _lavish_proc
    with _revive_lock:
        if lavish_up(port):
            return True
        if time.time() - _revive_last < REVIVE_COOLDOWN:
            return False
        _revive_last = time.time()
        exe = shutil.which(LAVISH_BINARY)
        if not exe:
            return False
        env = dict(os.environ, LAVISH_AXI_PORT=str(port))
        try:
            LAVISH_LOG.parent.mkdir(parents=True, exist_ok=True)
            log = LAVISH_LOG.open("a")
        except OSError:
            log = None
        try:
            _lavish_proc = subprocess.Popen(
                [exe, "server"], stdout=(log or subprocess.DEVNULL), stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        except OSError:
            return False
        finally:
            if log is not None:
                log.close()
        threading.Thread(target=_lavish_proc.wait, daemon=True).start()
        deadline = time.time() + REVIVE_WAIT
        while time.time() < deadline:
            if lavish_up(port):
                _revive_last = 0.0     # a revive that worked must not rate limit the next one
                return True
            time.sleep(0.25)
        return False


def lavish_origin(port: int, host: str | None, origin: str | None, referer: str | None) -> str:
    """The Origin to present to lavish for a same-origin browser request, else ""."""
    ours = host_of(host)
    if not ours or host_of(origin or referer) != ours:
        return ""
    return f"http://127.0.0.1:{port}"


def cut(response) -> None:
    """Shut the socket under an upstream answer down, so a read blocked on it returns.

    Closing the response instead would not do: a blocked read holds the buffer's lock for
    as long as it is blocked and `close()` waits for that same lock, so both threads would
    sit there until the upstream finally spoke, which is the thing being escaped. A
    shutdown is an operation on the socket rather than on one handle onto it, so every
    descriptor pointing at that socket sees it at once, which is how it reaches a read this
    thread holds nothing of. The descriptor is duplicated first, so closing this handle
    afterwards leaves the response's own where it was.
    """
    try:
        handle = socket.socket(fileno=os.dup(response.fileno()))
    except (AttributeError, OSError, ValueError):
        return      # the response closed itself first, and there is nothing left to cut
    try:
        handle.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    finally:
        handle.close()


def safe_child(root: Path, relative: str) -> Path | None:
    """`root/relative` when it stays under `root`, else None."""
    clean = posixpath.normpath("/" + relative).lstrip("/")
    target = (root / clean).resolve()
    root = root.resolve()
    return target if target == root or root in target.parents else None


class Handler(PlanRoute, CiRoute, CommentsRoute, VoiceTier, HouseTier, BaseHTTPRequestHandler):
    server_version = "keel-deck/1"
    pass_response = frozenset(PASS_RESPONSE)
    cfg: Config
    deck: deckstate.Deck
    app_dir: Path
    page_key: str = ""        # this process's page cookie (`keel/deckauth.py`), set in make_server

    def log_message(self, fmt, *args):  # quiet by default; errors still go to stderr
        return

    def handle(self) -> None:
        """A client that hangs up mid-reply (a reload, a closed tab, an aborted poll, a
        lavish stream the page stopped listening to) is not an error worth a traceback."""
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            global CLIENT_HANGUPS
            CLIENT_HANGUPS += 1

    def handle_one_request(self) -> None:
        """One request, with the body ceiling around EVERY route this server has.

        Here rather than at each `read_body` call site because there are several of them
        across modules (the deck's routes, the lavish proxy, the voice tier, the house tier):
        a rule that has to be remembered in several places is a rule with a hole in it.
        Nothing has replied yet at the point a body is read, so the refusal is this request's
        whole answer.
        """
        try:
            super().handle_one_request()
        except BodyTooLarge as error:
            self.refuse_body(error)

    # ----- replies -----

    def reply(self, status: int, body: bytes, content_type: str, cache: str = NO_STORE,
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def reply_json(self, status: int, payload) -> None:
        self.reply(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def reply_file(self, path: Path, content_type: str | None = None,
                   extra: dict | None = None, cache: str = NO_STORE) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.reply_json(404, {"ok": False, "error": "no such file"})
            return
        kind = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if kind.startswith("text/") and "charset" not in kind:
            kind += "; charset=utf-8"
        self.reply(200, body, kind, cache=cache, extra=extra)

    def takes_gzip(self) -> bool:
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def reply_app_file(self, path: Path, zip_ok: bool = True) -> None:
        """One of the page's own files, gzipped for a client that says it takes gzip (lane
        P: the shell's scripts and ELK went over the wire raw, 2.1 MB for a cold plan). The
        compressed bytes are kept per file and per mtime, so a deploy is seen at once. Each
        answer carries `file_tag` and `REVALIDATE`, and a matching If-None-Match is a 304
        (c-540). `zip_ok` is False for a file gzip cannot shrink (a segment's icons, c-549)."""
        zipped = zip_ok and self.takes_gzip()
        try:
            tag = file_tag(path, zipped)
        except OSError:
            return self.reply_json(404, {"ok": False, "error": "no such file"})
        if self.if_none_match() == tag:
            return self.not_modified(tag, REVALIDATE, vary=True)
        if not zipped:
            return self.reply_file(path, cache=REVALIDATE, extra={"ETag": tag, "Vary": "Accept-Encoding"})
        try:
            body = compressed(path)
        except OSError:
            return self.reply_json(404, {"ok": False, "error": "no such file"})
        kind = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith("javascript") or kind.endswith("json"):
            kind += "; charset=utf-8" if "charset" not in kind else ""
        self.reply(200, body, kind, cache=REVALIDATE,
                   extra={"Content-Encoding": "gzip", "Vary": "Accept-Encoding", "ETag": tag})

    # ----- relaying an upstream answer -----

    def client_gone(self) -> bool:
        """Has the client closed its end of this connection.

        A peer that has hung up is readable with nothing on it, which is what tells it
        apart from one that is merely quiet. The byte is peeked at rather than taken, so a
        client that did send something is left exactly as it was.
        """
        try:
            if not select.select([self.connection], [], [], 0)[0]:
                return False
            return not self.connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return True

    def until_hangup(self, response, stop: threading.Event, left: threading.Event) -> None:
        """Watch the client while `relay` pumps, and cut the upstream when it leaves."""
        while not stop.wait(STREAM_TICK):
            if self.client_gone():
                left.set()
                cut(response)
                return

    def relay(self, response) -> None:
        """Pump an upstream answer to the client until one of the two is done.

        A client that leaves is otherwise noticed only on the next write, and `/events/` is
        a channel that never ends and can be quiet for minutes at a time, so an abandoned
        one held the client's socket AND lavish's until the read timeout an hour away. The
        deck reopened that channel on every poll for a while, and two descriptors apiece is
        how this process ran out of them and could no longer spawn `claude` (card c-276).
        So the client's own end is watched for the whole relay, and its hangup cuts the
        read that is waiting on lavish.
        """
        stop, left = threading.Event(), threading.Event()
        watch = threading.Thread(target=self.until_hangup, args=(response, stop, left),
                                 name="proxy-hangup", daemon=True)
        watch.start()
        try:
            while True:
                chunk = response.read1(8192)
                if not chunk:
                    return
                self.wfile.write(chunk)
                self.wfile.flush()
        except http.client.HTTPException:
            # Lavish frames `/events/` in chunks, and a read cut in the middle of a chunked
            # answer raises IncompleteRead where a plain one returns nothing. After a cut
            # that is the client having left, and `handle` counts it as one.
            if left.is_set():
                raise BrokenPipeError("the client left mid-stream") from None
            raise
        finally:
            # Joined, not merely told to stop: the watch must be finished with `response`
            # before the caller closes it, or a cut could land on a reused descriptor.
            stop.set()
            watch.join(timeout=STREAM_TICK)

    # ----- routes -----

    def path_only(self) -> str:
        return self.path.split("?", 1)[0]

    def query(self) -> str:
        return self.path.split("?", 1)[1] if "?" in self.path else ""

    def harbor_redirect(self, path: str) -> bool:
        """Voice's own address (`[voice] app_url`, the Tailscale Service `harbor`) is this same
        server under another name, so a phone installs Voice as its own app rather than a
        shortcut inside the deck's `/` scope (2026-09-26). On that name `/` is Voice, and the
        deck's own pages (Voice's back link, `/?view=now`) go to the deck's address."""
        app = self.cfg.voice_app_url
        if path != "/" or not app:
            return False
        if deckauth.host_of(self.headers.get("Host")) != deckauth.host_of(app):
            return False
        query = self.query()
        if query and self.cfg.voice_deck_url:
            where = f"{self.cfg.voice_deck_url}/?{query}"
        else:
            where = VOICE_APP_PATH
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def do_GET(self):
        path = self.path_only()
        try:
            if self.harbor_redirect(path):
                return None
            if path in SHELL_PATHS or BOARD_PAGE.match(path):
                return self.reply_shell()
            if PLAN_PAGE.match(path) or FILE_PAGE.match(path):
                return self.reply_shell(PLAN_SHELL)
            if path in CONSOLE_PATHS:
                return self.reply_shell(CONSOLE_SHELL)
            if path in deckviews.FILLED:
                return self.reply_filled(deckviews.FILLED[path])
            if self.app_path(path):
                return self.reply_app_file(self.app_dir / self.app_path(path))
            if path == "/api/state":
                return self.get_state()
            if path == HEALTH_ROUTE:
                # F4: the verdict and the services, never a 304. It does not move the
                # state's revision (A-8), so a page holding a current state would never
                # see a new verdict through /api/state; it asks here once a minute.
                # `serve_head` (c-637): the code this deck runs, which a deploy waits to see
                return self.reply_json(200, {**health.current(self.cfg),
                                             "serve_head": STARTED_HEAD})
            if path == EVENTS_ROUTE:
                return self.get_events()
            if path == SETUP_ROUTE:
                return self.reply_json(200, {**onboarding.report(self.cfg), "boot": BOOT})
            if path == SETTINGS_ROUTE:
                return self.reply_json(200, settings.report(self.cfg))
            if path == HELLO_ROUTE:
                # moves the deck only when the answer changed (`Deck.heard`, r1.F7)
                return self.reply_json(200, {"hello": self.deck.heard(firstrun.hello(self.cfg))})
            match = CARD_ROUTE.match(path)
            if match:
                return self.get_card(match.group(1))
            match = PLAN_API.match(path)
            if match:
                return self.get_plan(match.group(1))
            match = CI_API.match(path)
            if match:
                return self.get_ci(match.group(1))
            match = COMMENTS_API.match(path)
            if match:
                return self.get_comments(match.group(1))
            match = ARTIFACT_ROUTE.match(path)
            if match:
                return self.get_artifact(match.group(1))
            match = ATLAS_ROUTE.match(path)
            if match:
                return self.get_atlas(match.group(1))
            match = BOARD_API.match(path)
            if match:
                return self.get_board(match.group(1))
            if path == BOARDS_LIST:
                return self.get_boards()
            if path == BOARDS_USES:
                return self.get_board_uses()
            match = BOARD_ASK_TURN.match(path)
            if match:
                return self.get_board_ask(match.group(2))
            match = SEGMENT_APP.match(path)
            if match:
                return self.get_segment_app(match.group(1), match.group(2) or "")
            if SEGMENT_ROUTE.match(path):
                return self.segment_reply(segments.get(self.cfg, path))
            if VOICE_ROUTE.match(path):
                return self.voice(self.command)
            if path == HOUSE_PREFIX:
                return self.house("GET")
        except Exception:  # noqa: BLE001 - a read never takes the server down
            traceback.print_exc(file=sys.stderr)
            return self.reply_json(500, {"ok": False, "error": "the read failed; see the server log"})
        self.proxy("GET")

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if self.path_only() == "/api/action":
            return self.post_action()
        match = BOARD_INBOX.match(self.path_only())
        if match:
            return self.post_board_inbox(match.group(1))
        match = BOARD_ASK.match(self.path_only())
        if match:
            return self.post_board_ask(match.group(1))
        if self.path_only().startswith(HOUSE_PREFIX):
            # Held for the code-moved restart, which waits for it (`keel/restart.py`).
            with restart.CALLS.held(restart.HOUSE_CALL):
                return self.house("POST")
        if VOICE_ROUTE.match(self.path_only()):
            return self.voice("POST")
        if SEGMENT_ROUTE.match(self.path_only()):
            return self.post_segment()
        self.proxy("POST")

    # ----- the page's own proof (c-451) -----

    def reply_shell(self, name: str = "index.html") -> None:
        """The page, with this process's cookie on it: the page's GET of the shell is how
        the page comes to hold the key its POSTs are asked for. The plan and outcome pages
        are a shell of their own (`PLAN_SHELL`) and get the same cookie. The deck's shell is
        filled from its manifest (c-634)."""
        cookie = {"Set-Cookie": self.page_cookie()}
        if name != "index.html":
            return self.reply_file(self.app_dir / name, extra=cookie)
        try:
            body = deckviews.rendered(self.app_dir, name).encode("utf-8")
        except (OSError, deckviews.ManifestError) as error:
            return self.reply(500, f"the deck's manifest: {error}\n".encode(), "text/plain; charset=utf-8")
        self.reply(200, body, "text/html; charset=utf-8", cache=NO_STORE, extra=cookie)

    def app_path(self, path: str) -> str | None:
        """The app file a path names: `APP_FILES`, or a deck script the manifest lists now."""
        return APP_FILES.get(path) or deckviews.served(self.app_dir).get(path)

    def reply_filled(self, name: str) -> None:
        """`sw.js`, filled from the manifest, under the app files' rule (c-540): an ETag over
        the file and the manifest together, `no-cache`, and gzip for a client that takes it."""
        zipped = self.takes_gzip()
        try:
            tag = deckviews.filled_tag(self.app_dir, name, zipped)
        except OSError:
            return self.reply_json(404, {"ok": False, "error": "no such file"})
        if self.if_none_match() == tag:
            return self.not_modified(tag, REVALIDATE, vary=True)
        try:
            body = deckviews.rendered(self.app_dir, name).encode("utf-8")
        except (OSError, deckviews.ManifestError) as error:
            return self.reply_json(500, {"ok": False, "error": f"the deck's manifest: {error}"})
        extra = {"ETag": tag, "Vary": "Accept-Encoding"}
        if zipped:
            body = gzip.compress(body, compresslevel=6, mtime=0)
            extra["Content-Encoding"] = "gzip"
        self.reply(200, body, "text/javascript; charset=utf-8", cache=REVALIDATE, extra=extra)

    def page_cookie(self) -> str:
        return deckauth.cookie_header(self.server.server_address[1], self.page_key, self.headers)

    def from_the_page(self) -> bool:
        return deckauth.from_the_page(self.headers, self.server.server_address[1], self.page_key)

    def refuse_unproven(self, verb=None, unread: bool = False) -> None:
        """403 for a request that acts as him without the page's proof. `renew` tells the
        page it may fetch the shell once for a fresh cookie and try again (`K.post`)."""
        if unread:
            self.close_connection = True    # the body is still on the socket
        # Another page in another tab is told what it always was, and is offered nothing.
        payload = ({"ok": False, "error": deckauth.REFUSED, "renew": True} if same_origin(self.headers)
                   else {"ok": False, "error": segments.FOREIGN})
        self.reply_json(403, dict(payload, verb=verb) if verb is not None else payload)

    def post_segment(self) -> None:
        """A segment's own drop box. The origin check is the door's, the rest is the tier's."""
        try:
            reply = segments.post(self.cfg, self.path, self.headers, self.rfile,
                                  same_origin(self.headers))
        except Exception:  # noqa: BLE001 - a bad drop never takes the server down
            traceback.print_exc(file=sys.stderr)
            reply = segments.refuse(500, "storing it failed; see the server log", unread=False)
        if reply is None:
            reply = segments.refuse(404, "not a segment route", unread=False)
        self.segment_reply(reply)

    def segment_reply(self, reply) -> None:
        if reply.unread:
            # The body was never read, so this connection cannot be reused: the unread
            # bytes would be parsed as the next request's own request line.
            self.close_connection = True
        # A SEGMENT'S DATA IS WRITTEN BY ITS FETCHER, and never sniffed into a page; an HTML or SVG one is sandboxed (c-451, round 3).
        self.reply(reply.status, reply.body, reply.content_type,
                   extra=artifacts.served_headers(reply.content_type))

    def do_PUT(self):
        if VOICE_ROUTE.match(self.path_only()):
            return self.voice("PUT")
        if SEGMENT_ROUTE.match(self.path_only()):
            return self.segment_reply(segments.refuse(404, "not a segment route", unread=False))
        self.proxy("PUT")

    def do_DELETE(self):
        if VOICE_ROUTE.match(self.path_only()):
            return self.voice("DELETE")
        if SEGMENT_ROUTE.match(self.path_only()):
            return self.segment_reply(segments.refuse(404, "not a segment route", unread=False))
        self.proxy("DELETE")

    # ----- the two documents the page holds, and what says they moved -----

    def if_none_match(self) -> str:
        return (self.headers.get("If-None-Match") or "").strip()

    def not_modified(self, tag: str, cache: str = NO_STORE, vary: bool = False) -> None:
        """A 304 carries no body, so the page renders nothing and draws nothing."""
        self.send_response(304)
        self.send_header("ETag", tag)
        self.send_header("Cache-Control", cache)
        if vary:
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()

    def state_asked(self) -> tuple[str | None, bool, str | None, str | None, bool]:
        """`?scope=`, `?archived=1`, `?card=<id>`, the card the page has open (c-540),
        `?part=live|done` (c-549), and `?steps=1`, the Start view's ask for the first-run
        steps (c-678 review). An unknown scope is the whole document, the one a machine
        reader asks for with no query, and a part means nothing without a scope."""
        asked = urllib.parse.parse_qs(self.query())
        scope = (asked.get("scope") or [""])[0]
        if scope not in deckstate.SCOPES:
            return None, False, None, None, True
        card = (asked.get("card") or [""])[0]
        part = (asked.get("part") or [""])[0]
        return (scope, (asked.get("archived") or [""])[0] == "1",
                card if re.match(r"^c-\d+$", card) else None,
                part if part in deckstate.PARTS else None,
                (asked.get("steps") or [""])[0] == "1")

    def json_tag(self, rev: str, *parts: str) -> str:
        """A JSON document's ETag: its revision, what was asked, and the encoding."""
        said = "-".join(part for part in (*parts, "gz" if self.takes_gzip() else "") if part)
        return f'"{rev}-{said}"' if said else f'"{rev}"'

    def get_state(self) -> None:
        scope, archived, card, part, steps = self.state_asked()
        if part == "done":
            return self.get_done_part(scope, archived, card, steps)
        tag = self.json_tag(self.deck.rev(), scope or "", "a" if archived else "", card or "", part or "",
                            "s" if steps and scope else "")
        if self.if_none_match() == tag:
            return self.not_modified(tag, vary=True)
        doc = self.deck.state(scope, archived, card, steps)
        if part == "live":
            doc = deckstate.part_of(doc, part, card)
        self.reply_json_tagged(200, with_code_state(self.cfg, doc), tag)

    def get_done_part(self, scope: str, archived: bool, card: str | None, steps: bool = False) -> None:
        """The done cards alone (c-549), tagged on WHAT THEY ARE rather than on the board's
        revision: a refresh that moved no done card is a 304, which is the point of the
        split, since the live part is the one that changes."""
        doc = deckstate.part_of(self.deck.state(scope, archived, card, steps), "done", card)
        held = hashlib.sha1(json.dumps(doc["cards"], sort_keys=True).encode()).hexdigest()[:16]
        tag = self.json_tag(held, scope, "a" if archived else "", card or "", "done")
        if self.if_none_match() == tag:
            return self.not_modified(tag, vary=True)
        self.reply_json_tagged(200, doc, tag)

    def get_card(self, card_id: str) -> None:
        rev = self.deck.card_rev(card_id)
        # the detail lists the card's files (c-719), which a house writes with no board event:
        # read once from the card's own row (its named output counts), stamped, and handed on
        files = self.deck.card_files_of(card_id) if rev else None
        tag = self.json_tag(f"{rev}-{cardfiles.stamp_of(files or [])}") if rev else ""
        if tag and self.if_none_match() == tag:
            return self.not_modified(tag, vary=True)
        try:
            self.reply_json_tagged(200, self.deck.detail(card_id, files), tag)
        except Exception as error:  # noqa: BLE001 - an unknown id is the common case
            self.reply_json(404, {"ok": False, "error": str(error).splitlines()[0]})

    def get_events(self) -> None:
        """The event stream: one thread, this one, for as long as this subscriber stays.

        It waits on its own queue (what a writer in THIS process published) and, on every
        wake, looks at the two numbers another process could have moved: the deck's
        revision and the size of the one board this page has open. So a `keel board push`
        from a house's shell reaches his phone in a quarter second rather than in the five
        the board's own poll used to cost.

        Nothing here holds a lock a writer needs: the hub's own lock covers its subscriber
        list and nothing else, and the sweep is two stats.
        """
        asked = urllib.parse.parse_qs(self.query())
        board_id = (asked.get("board") or [""])[0]
        if board_id and not BOARD_ID.match(board_id):
            board_id = ""
        # THE PLAN THIS PAGE HAS OPEN, watched the way its board is: a house rewriting its
        # plan file is no board event, so without this the page would not see a revision.
        self.plan_card = (asked.get("plan") or [""])[0]
        if not re.match(r"^c-\d+$", self.plan_card):
            self.plan_card = ""
        stream = deckevents.HUB.open()
        watcher = getattr(self.deck, "watcher", None)
        if watcher is not None:
            watcher.ensure()        # the live strip reads only while somebody watches (c-599)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", NO_STORE)
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.pump_events(stream, board_id)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            deckevents.HUB.close(stream)

    def pump_events(self, stream, board_id: str) -> None:
        """One subscriber's loop, until it is closed or its client has gone.

        The hangup check runs on a quiet queue AND every `HANGUP_EVERY` lines. A busy
        board keeps the queue full, so a check that waited for a quiet moment would not
        run at all while the writes kept coming. A write to a socket whose peer has gone
        usually raises before that (and `get_events` catches it), but "usually" depends on
        how much the send buffer will absorb first, and a subscriber nobody is reading is
        one this process is holding two descriptors open for.
        """
        # WHAT THIS STREAM HAS ALREADY PUBLISHED, so a sweep that finds it unchanged says
        # nothing at all. It starts at what the route would answer right now, which is what
        # the page already holds from the fetch that opened this.
        #
        # THE TWO HALVES ARE TRACKED APART. `Deck.rev` carries a fifteen second clock, for
        # the two inputs that are neither a write nor the board (the drain log, the usage
        # tee), and the page answers a `state` line with a whole `/api/state` fetch. So a
        # deck nobody was touching refetched the document four times a minute to move some
        # ages by fifteen seconds, and a test about the sweep's silence failed one run in
        # five. The clock is a `tick` now: the page re-renders what it already holds and
        # fetches nothing.
        written, clock = self.deck.rev_parts()
        cursor = board_lines(self.cfg, board_id)
        planned = self.plan_file_stamp()
        plan_rev = self.plan_card_rev()
        said = time.monotonic()
        since_check = 0
        while not stream.closed:
            line = stream.get(deckevents.SWEEP_SECONDS)
            if line:
                self.say_event(line)
                said = time.monotonic()
                since_check += 1
                if since_check >= deckevents.HANGUP_EVERY:
                    since_check = 0
                    if self.client_gone():
                        return
                continue
            since_check = 0
            if self.client_gone():
                return
            now_written, now_clock = self.deck.rev_parts()
            moved = now_written != written
            if moved:
                # A WRITE CARRIES THE CLOCK WITH IT, so the page is never told `state` and
                # then `tick` about a step that `state` already carried.
                written, clock = now_written, now_clock
                self.say_event(f"state {written}.{clock}")
                said = time.monotonic()
            elif now_clock != clock:
                # At most once per step, because it is only said when it CHANGES; the sweep
                # runs four times a second and the step lasts fifteen.
                clock = now_clock
                self.say_event(f"tick {clock}")
                said = time.monotonic()
            if moved and plan_rev is not None:
                # ANOTHER PROCESS'S WRITE (c-579): a house's `kb reply` writes the board
                # itself, so the hub never named the card and the plan page, which drops
                # `state`, showed his answer only on reload. The stamp moving is the cue.
                now_rev = self.plan_card_rev()
                if now_rev and now_rev != plan_rev:
                    plan_rev = now_rev
                    self.say_event(f"card {self.plan_card} {plan_rev}")
                    said = time.monotonic()
            now_planned = self.plan_file_stamp(reread=moved)
            if now_planned != planned:
                planned = now_planned
                self.say_event(f"plan {self.plan_card} {planned}")
                said = time.monotonic()
            at = board_lines(self.cfg, board_id)
            if at != cursor:
                cursor = at
                self.say_event(f"board {board_id} {cursor}")
                said = time.monotonic()
            if time.monotonic() - said > deckevents.PING_SECONDS:
                self.say_event("ping")
                said = time.monotonic()

    def plan_card_rev(self) -> str | None:
        """The open plan card's `card_rev` without the clock, "" when it went away, None when
        none is open. A house elsewhere moves its full rev every clock step, which is the
        pane's cue and not a change to the plan page."""
        if not getattr(self, "plan_card", ""):
            return None
        try:
            return self.deck.card_rev(self.plan_card) or ""
        except Exception:  # noqa: BLE001 - a card that went away has nothing to say
            return ""

    def plan_file_stamp(self, reread: bool = False) -> str:
        """The open plan's file stamp (`?plan=` on the stream), or "" when none is open.

        The card is read once and again only when the state moved (its plan_ref may have),
        so the sweep's own cost is one stat, as the board's is."""
        if not getattr(self, "plan_card", ""):
            return ""
        if reread or not hasattr(self, "plan_of"):
            board = self.deck.board_factory()
            try:
                self.plan_of = board.get(self.plan_card)
            except Exception:  # noqa: BLE001 - a card that went away has no plan to watch
                self.plan_of = None
            finally:
                board.close()
        return plan_stamp(self.cfg, self.plan_of)

    def say_event(self, line: str) -> None:
        self.wfile.write(f"data: {line}\n\n".encode())
        self.wfile.flush()

    def reply_json_tagged(self, status: int, payload, tag: str) -> None:
        """A tagged JSON document, gzipped for a client that takes gzip (c-540: the state
        was 2 MB raw and 0.48 MB gzipped, and only the page's files were being compressed)."""
        body, extra = json.dumps(payload).encode(), {"Vary": "Accept-Encoding"}
        if tag:
            extra["ETag"] = tag
        if self.takes_gzip() and len(body) >= GZIP_FLOOR:
            body = gzip.compress(body, compresslevel=5, mtime=0)
            extra["Content-Encoding"] = "gzip"
        self.reply(status, body, "application/json; charset=utf-8", extra=extra)

    def get_artifact(self, token: str) -> None:
        path = artifacts.untoken(self.cfg, token)
        if path is None or not path.is_file():
            return self.reply_json(404, {"ok": False, "error": "no such artifact"})
        if path.stat().st_size > artifacts.cap(self.cfg, path):
            return self.reply_json(413, {"ok": False, "error": f"{path.name} is larger than the deck serves; open it at the desk"})
        if artifacts.board_file(self.cfg, path):
            # A BOARD FILE IS ALWAYS A DOWNLOAD AND NEVER A PAGE. Its bytes were chosen by
            # a house, which writes what it likes into its own worktree, so serving one as
            # `text/html` or `image/svg+xml` would be that house's script running in the
            # deck's OWN origin, where the approve verbs live, under a URL he was invited
            # to open. The type is forced rather than filtered by suffix, sniffing is off,
            # and the disposition is an attachment: three rules, no list of dangerous
            # extensions to keep up to date, and nothing to be right about per file.
            return self.reply_file(path, artifacts.DOWNLOAD_TYPE,
                                   extra=artifacts.download_headers(path))
        raw = "raw=1" in (self.path.split("?", 1)[1] if "?" in self.path else "")
        if artifacts.kind(path) == "markdown" and not raw:
            page = artifacts.markdown_html(path.read_text(errors="replace"), path.name,
                                           base_dir=path.parent, cfg=self.cfg)
            kind = "text/html; charset=utf-8"
            return self.reply(200, page.encode(), kind, extra=artifacts.served_headers(kind))
        kind = artifacts.mime(path) if not raw else "text/plain; charset=utf-8"
        self.reply_file(path, kind, extra=artifacts.served_headers(kind))

    def get_atlas(self, slug: str | None) -> None:
        """The Atlas page list, or one page as {slug, title, html}."""
        try:
            self.reply_json(200, {"pages": atlas.index(self.cfg)} if not slug
                            else atlas.page(self.cfg, slug))
        except atlas.AtlasError as error:
            self.reply_json(404, {"ok": False, "error": str(error)})

    def get_board(self, board_id: str) -> None:
        """One board, and the accepted lines after `?since=<line>`.

        This is the live channel: an open board page asks for what came after the last
        line it holds, on the deck's own polling cadence and only while it is visible, and
        appends what arrived. A cursor of 0 is the whole board, which is also how a saved
        one is read.
        """
        query = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
        try:
            since = int((query.get("since") or ["0"])[0])
        except ValueError:
            since = 0
        try:
            self.reply_json(200, boards.api_board(self.cfg, board_id, since))
        except boards.BoardError as error:
            # A BOARD HE DELETED IS `410 Gone` with who and when (BD-1), so the page can
            # offer him Restore rather than saying the id was never there.
            deleted = boardtrash.deleted_block(self.cfg, board_id)
            self.reply_json(410 if deleted else 404, {"ok": False, "error": str(error),
                                                      "id": board_id, "deleted": deleted})

    def get_boards(self) -> None:
        """Every board with its card, and `?q=` searched across them (C5). A read, open
        exactly as one board's read is. `?deleted=1` is the trash (BD-3)."""
        asked = urllib.parse.parse_qs(self.query())
        query = asked.get("q") or [""]
        deleted = (asked.get("deleted") or [""])[0] in ("1", "true")
        self.reply_json(200, boardlist.listing(self.cfg, query[0], deleted=deleted))

    def get_board_uses(self) -> None:
        """Which plans and outcomes embed these boards, asked by the delete's confirm (BD-2)."""
        asked = urllib.parse.parse_qs(self.query()).get("ids") or [""]
        ids = [part for part in asked[0].split(",") if BOARD_ID.match(part)][:200]
        board = self.deck.board_factory()
        try:
            self.reply_json(200, boarduses.uses(self.cfg, board, ids))
        finally:
            board.close()

    def post_board_inbox(self, board_id: str) -> None:
        """One file he dropped on the board (K7). The origin check is the door's, exactly
        as a segment's drop box is; the caps, the naming and the frame are the board's. It
        notes the card as him, so it asks for the page's proof first (c-451)."""
        if not self.from_the_page():
            return self.refuse_unproven(unread=True)
        board = open_board(self.cfg)
        try:
            reply = boards.inbox(self.cfg, board, board_id, self.headers, self.rfile,
                                 same_origin(self.headers), self.query())
        except Exception:  # noqa: BLE001 - a bad drop never takes the server down
            traceback.print_exc(file=sys.stderr)
            reply = boardfiles.refuse(500, "storing it failed; see the server log", unread=False)
        finally:
            board.close()
        self.deck.drop()          # the card gained a note, so the cached state is stale
        self.segment_reply(reply)

    def post_board_ask(self, board_id: str) -> None:
        """One question for this board's house; the turn id the page then polls on. A turn
        into a house in his words is his, so it asks for the page's proof (c-451)."""
        if not self.from_the_page():
            return self.refuse_unproven(unread=True)
        try:
            body = json.loads(self.read_body() or b"{}")
        except ValueError:
            return self.reply_json(400, {"ok": False, "error": "the body is not JSON"})
        try:
            record = boards.read_record(self.cfg, board_id)
        except boards.BoardError as error:
            return self.reply_json(404, {"ok": False, "error": str(error)})
        try:
            started = boardask.start(self.cfg, record, str((body or {}).get("text") or ""))
        except boardask.AskError as refusal:
            return self.reply_json(409, {"ok": False, "error": str(refusal)})
        self.reply_json(200, {"ok": True, **started})

    def get_board_ask(self, turn: str) -> None:
        answer = boardask.result(turn)
        if answer is None:
            return self.reply_json(404, {"ok": False, "error": "no turn by that id"})
        self.reply_json(200, {"ok": True, **answer})

    def get_segment_app(self, name: str, rest: str) -> None:
        segment = self.cfg.segment_dir(name)
        if segment is None:
            return self.reply_json(404, {"ok": False, "error": "no such segment"})
        root = segment / "app"
        target = safe_child(root, rest or "index.html")
        if target is not None and target.is_dir():
            target = target / "index.html"
        if target is None or not target.is_file():
            return self.reply_json(404, {"ok": False, "error": "no such segment file"})
        # A SEGMENT'S OWN SHELL hands out the page's cookie too (c-451, review item 3): the
        # voice app is its own app on this origin, and its websocket asks for the cookie.
        # Segment apps are this repo's code, not a house's.
        if target.suffix.lower() in (".html", ".htm"):
            return self.reply_file(target, extra={"Set-Cookie": self.page_cookie()})
        # EVERY OTHER FILE IS THE DECK'S OWN RULE (c-549): gzipped, an ETag, kept and asked
        # about. The voice page's thirteen files went raw and `no-store`, about 150 KB again on
        # every open, while the deck's own files had been 304s since c-540.
        self.reply_app_file(target, zip_ok=target.suffix.lower() in SEGMENT_ZIPPED)

    def read_body(self) -> bytes:
        """The request body, refused above the door's own ceiling.

        `Content-Length` used to be read whole with nothing above it, so one POST was as
        much memory as it cared to NAME: the caps that existed were the board's (400 lines,
        240 characters a string) and they are all inside a body that had already been read.
        The ceiling is above every legitimate body this server has, and it is checked before
        a byte is taken off the socket.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise BodyTooLarge(length)
        return self.rfile.read(length) if length else b""

    def refuse_body(self, error: "BodyTooLarge") -> None:
        """Say no to an over-large body, and end the connection.

        The connection cannot be reused: the body was never read, so the bytes still on the
        socket would be parsed as the next request's own request line. The same rule the
        segment tier keeps for a refusal it did not drain.
        """
        self.close_connection = True
        self.reply_json(413, {"ok": False, "error": f"that body is larger than the deck "
                                                    f"accepts ({MAX_BODY // (1024 * 1024)}MB)"})

    def post_action(self) -> None:
        """One action, held as `restart.DECK_ACTION` from its body to its reply (c-637
        review): a code-moved exec waits until the page has its answer."""
        with restart.CALLS.held(restart.DECK_ACTION):
            self.act_and_reply()

    def act_and_reply(self) -> None:
        try:
            body = json.loads(self.read_body() or b"{}")
        except ValueError:
            return self.reply_json(400, {"ok": False, "error": "the body is not JSON"})
        if not isinstance(body, dict):
            return self.reply_json(400, {"ok": False, "error": "the body must be an object"})
        if self.refused_unproven(body):
            return
        setup = body.get("verb") in actions.SETUP_VERBS and body.get("verb") not in firstrun.UNLOCKED
        if setup and not SETUP_LOCK.acquire(blocking=False):
            return self.reply_json(409, {"ok": False, "verb": body.get("verb"), "error": SETUP_BUSY})
        board = open_board(self.cfg)
        restarting, followed, stamp, failed = False, False, config_stamp(self.cfg), None
        try:
            if body.get("verb") == "restart":
                threading.Timer(0.5, restart_process).start()
                result = {"restarting": True, "head": merging.code_head(self.cfg.root)}
            else:
                result = actions.act(self.cfg, board, body)
                if body.get("verb") in onboarding.CONFIG_VERBS:
                    restarting, followed = self.follow_config(bool(isinstance(result, dict) and result.get("voice"))), True
                    result = dict(result, restarting=restarting, reloaded=not restarting)
        except (actions.ActionError, ValueError) as error:
            refused = {"ok": False, "verb": body.get("verb"), "error": str(error)}
            if getattr(error, "detail", None):
                refused["detail"] = error.detail        # c-678: what the page draws beside the sentence
            failed = (409, refused)
        except Exception as error:  # noqa: BLE001 - say what failed; never take the server down
            traceback.print_exc(file=sys.stderr)
            failed = (500, {"ok": False, "verb": body.get("verb"), "error": str(error).splitlines()[0] if str(error) else type(error).__name__})
        finally:
            board.close()
            if not followed and stamp is not None and config_stamp(self.cfg) != stamp:
                # r1.F5: a verb that wrote the config and then failed still leaves the deck on
                # the file as it is now, never on the one before it
                restarting = self.follow_config(deckreload.voice_moved(self.cfg))
            if setup and not restarting:
                SETUP_LOCK.release()
            if not actions.reads_only(body):
                self.deck.drop()
        if failed:
            # answered once the deck is on the config as it is now (r1.F5)
            return self.reply_json(*failed)
        # The page is TOLD, rather than finding out on its next poll. `deck.drop` above
        # already said the state moved; this names the card, so a pane open on it refetches
        # and every other tab reads the line and drops it.
        card_id = body.get("id")
        if isinstance(card_id, str) and not actions.reads_only(body):
            rev = self.deck.card_rev(card_id)
            if rev:
                deckevents.HUB.card(card_id, rev)
        self.reply_json(200, {"ok": True, "verb": body.get("verb"), "result": result})

    def follow_config(self, voice_changed: bool) -> bool:
        """The config changed under this process: read it in place when it can be (c-729,
        `keel/deckreload.py`), else exec again once quiet so the deck reads it, with the setup
        lock held until the exec so no second change lands meanwhile. True when it restarts.
        The drain sees the file move (`drain.config_moved`)."""
        if not voice_changed and deckreload.reload(type(self), self.deck):
            return False
        schedule_restart(voice_changed)
        return True

    def refused_unproven(self, body: dict) -> bool:
        """Refuse a body that acts as him without the page's proof: True when it was refused
        (and answered), False when it may go on. Every action runs with the deck's own token,
        so it is the page's alone (`actions.human_path`); a body carrying a `caller` is
        refused (`actions.refuse_caller`).
        """
        verb = body.get("verb")
        try:
            actions.refuse_caller(body)
            human = actions.human_path(body)
        except actions.ActionError as error:
            self.reply_json(409, {"ok": False, "verb": verb, "error": str(error)})
            return True
        if human and not self.from_the_page():
            self.refuse_unproven(verb)
            return True
        return False

    # ----- the lavish proxy -----

    def open_lavish(self, request: urllib.request.Request, method: str, port: int):
        """Lavish's answer, starting lavish first when it has gone to sleep.

        Only a connection failure revives: an HTTP error is lavish's own answer and must be
        relayed. The retry is guarded by `lavish_up` as well as by the revive's own return,
        because a revive answers true when lavish was already up, and a connection failure
        against a lavish that is up is some other transient thing. Re-sending then would
        post the human's answer twice.
        """
        try:
            return urllib.request.urlopen(request, timeout=3600)
        except urllib.error.HTTPError:
            raise
        except OSError:
            if not by_a_person(method, self.path_only()) or lavish_up(port) or not lavish_revive(port):
                raise
            return urllib.request.urlopen(request, timeout=3600)

    def proxy(self, method: str) -> None:
        """Hand the request to lavish on this machine."""
        body = self.read_body() if method in ("POST", "PUT") else None
        port = self.cfg.lavish_port
        try:
            return self.forward(method, body, f"http://127.0.0.1:{port}", self.path)
        except UpstreamAway:
            pass
        self.reply_json(503, {"ok": False, "error": f"not a deck route, and nothing answers on lavish port {port}"})

    def rewriter(self, method: str, kind: str):
        """What to do to a whole upstream body before it goes out, or None to stream it.

        A lavish page gets the deck's phone layer. One document, read whole and handed back
        with two tags in it; everything else, and `/events/` above all (a channel that never
        ends), keeps streaming untouched."""
        if not lavishlayer.wants(method, self.path_only(), kind):
            return None
        return lambda page: lavishlayer.inject(page, kind)

    def forward(self, method: str, body: bytes | None, base: str, path: str) -> None:
        """Stream one upstream answer to the client. UpstreamAway when nothing answered,
        before a byte went out, so the caller may try elsewhere or say so."""
        port = self.cfg.lavish_port
        request = urllib.request.Request(base + path, data=body, method=method)
        for name in PASS_REQUEST:
            if self.headers.get(name):
                request.add_header(name, self.headers[name])
        origin = lavish_origin(port, self.headers.get("Host"), self.headers.get("Origin"), self.headers.get("Referer"))
        if origin:
            request.add_header("Origin", origin)
            request.add_header("Referer", origin + path)
        answering = False   # once headers have gone out, a failure is the client's, not lavish's
        try:
            with self.open_lavish(request, method, port) as response:
                # The validators go with a body that is rewritten: a conditional request is
                # never forwarded upstream, so nothing here answers 304 anyway.
                kind = response.headers.get("Content-Type", "")
                rewrite = self.rewriter(method, kind)
                self.send_response(response.status)
                for name, value in response.headers.items():
                    if name.lower() not in PASS_RESPONSE:
                        continue
                    if rewrite and name.lower() in ("etag", "last-modified"):
                        continue
                    self.send_header(name, value)
                for name, value in self.house_written_headers(path, kind).items():
                    self.send_header(name, value)
                answering = True
                if rewrite:
                    page = rewrite(response.read())
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    if method != "HEAD":
                        self.wfile.write(page)
                    return
                self.end_headers()
                self.relay(response)
        except (BrokenPipeError, ConnectionResetError):
            raise   # the client left; `handle` counts it and says nothing
        except urllib.error.HTTPError as error:
            with error:
                payload = error.read()
            kind = error.headers.get("Content-Type", "text/plain")
            self.reply(error.code, payload, kind, extra=self.house_written_headers(path, kind))
        except (OSError, urllib.error.URLError):
            if answering:
                raise BrokenPipeError("the client left mid-stream")   # a 503 now would go to nobody
            raise UpstreamAway(base) from None

    def house_written_headers(self, upstream_path: str, kind: str) -> dict:
        """The sandbox and nosniff (`artifacts.served_headers`) for a proxied answer whose
        bytes a house chose, served in THIS origin; nothing for anything else.

        `/artifact/<key>/...` is the plan lavish renders in its own sandboxed frame (c-451,
        round 3), and it is a URL too: opened as a whole page it ran in the deck's origin,
        with his cookie. Lavish's own pages (`/session/`, its
        scripts, `/events/`) are its code and talk to it same-origin, so they are left
        alone, and so is the phone layer injected into them.
        """
        paths = (self.path_only(), upstream_path.split("?", 1)[0])
        if not any(p.startswith(HOUSE_WRITTEN) for p in paths):
            return {}
        return artifacts.served_headers(kind)


class UpstreamAway(Exception):
    """Nothing answered upstream, and nothing has been sent to the client yet."""


class BurstServer(ThreadingHTTPServer):
    """A threading server whose listen backlog is the system's. The shell loads some 25 files
    at once, and `tailscale serve` opens a connection for each. socketserver's default
    backlog is 5, and macOS resets a connection past it (Linux drops the SYN and the client
    retries), so the phone's deck came up blank with 502s on his Mac (2026-10-03)."""

    request_queue_size = socket.SOMAXCONN


class DeckServer(BurstServer):
    """The deck's HTTP server, which also lets go of what its deck holds open when it
    closes: the board-stamp connection `Deck.board_stamp` keeps for the life of the
    process. Left to the collector, it was closed whenever that ran, with a
    `ResourceWarning: unclosed database` printed inside some later test's output."""

    deck: deckstate.Deck | None = None

    def server_close(self) -> None:
        super().server_close()
        deck = self.deck
        if deck is not None:
            deck.watcher.close()        # the live strip's reads end with the server (c-599)
            deck.kept.close()           # and so do the kept readings' refreshes (c-638)
            with deck.stamp_lock:
                if deck.stamp_conn is not None:
                    deck.stamp_conn.close()
                    deck.stamp_conn = None
                # AND IT STAYS CLOSED. An event stream's pump is a daemon thread that can
                # outlive the server by a poll, and it asks for the revision: pinning the
                # memo's age makes it answer the last stamp rather than open the connection
                # again for nobody to close. (A `Deck.close()` in `keel/deckstate.py` would
                # say this in the deck's own words; that file was another lane's tonight.)
                deck.stamped = deck.stamped or "0."
                deck.stamped_at = float("inf")


def make_server(cfg: Config, port: int | None = None, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    config_module.guard_port(cfg, port if port is not None else cfg.serve_port)
    deck = deckstate.Deck(cfg)
    handler = type("BoundHandler", (Handler,), {
        "cfg": cfg, "deck": deck, "app_dir": cfg.root / "app",
        # A NEW KEY PER PROCESS (c-451): a restart rotates it, and the page renews.
        "page_key": deckauth.mint()})
    global STARTED_HEAD
    STARTED_HEAD = merging.code_head(cfg.root)
    server = DeckServer((host, port if port is not None else cfg.serve_port), handler)
    server.deck = deck
    server.daemon_threads = True
    return server


def run(cfg: Config, port: int | None = None, follow: bool = True) -> None:
    """The deck. `follow` (c-637): exec onto the checkout's new code when it moves, which is
    off when the drain runs in this process (`cli.role_run`), since the drain's restart
    between its passes is the whole process's."""
    server = make_server(cfg, port)
    print(f"keel serve: http://127.0.0.1:{server.server_address[1]}/", file=sys.stderr, flush=True)
    # THIS PROCESS OWNS THE VOICE CONVERSATIONS (V12), so it also owns their expiry and
    # their end. The reaper closes one that has gone quiet for as long as the hold lasts;
    # `close_all` is the tidy exit, and the untidy one is covered too, because a
    # conversation's stdin is this process's pipe and closing it ends the `claude`.
    SESSIONS.watch(cfg.voice_hold_seconds)
    if follow:
        threading.Thread(target=follow_code, args=(cfg.root, STARTED_HEAD), name="follow-code",
                         daemon=True).start()
    try:
        server.serve_forever()
    finally:
        SESSIONS.close_all()
        server.server_close()
