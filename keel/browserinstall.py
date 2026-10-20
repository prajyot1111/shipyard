"""Installing Keel's browser from the first run (c-678): one background download, its
progress, and the sentence it says when it stopped.

`keel/browser.py` says where the browser lives and whether it is there; `bin/keel-browser
install` is what puts it there (playwright-core, then one Chromium, about 400 MB). This
module is the page's half: the A browser for sessions step starts that command by the
user's tap and shows how far it is.

- `node()`: "Node.js 20 or newer", since the tool is a Node script. The version is read
  from `node --version`.
- `start(cfg)` (`firstrun.browser.install`): runs the tool detached from the deck, so a
  deck that restarts mid-download does not end it, with its output in `install.log` and its
  process id in `install.pid`, both in the browser's own folder. One download at a time.
  The download's own shell writes that pid, before the tool runs, and removes the file as
  its last command. A file left behind (a reboot, a kill) is not trusted: a download counts
  as running only when the pid is alive AND its command line is the installer's
  (`is_installer`), and a file that fails either is cleared (review F7).
- `status(cfg)`: `waiting` (never asked), `downloading` (the process is alive, with how far
  the download is, below), `ready` (`browser.gather` finds the package and a Chromium
  build), or `failed` (the process ended and the browser is not there: "The download
  stopped: <the tool's last line>. Chromium had reached N% of X MiB."). Try again is `start`
  again.

**How far it is comes from the downloader's own lines** (c-757, `progress`). It was the
size of the browser's folder against a fixed 400 MB, and on the first teammate's setup
that read 0, then 3, then done: the pinned Playwright writes the archive it is fetching
into the system's temp folder (`browserFetcher.ts`, a `playwright-download-` folder under
`os.tmpdir()`), not into the browser's folder, so all the folder held for the whole
download was the 13 MB package, 3% of 400. The archive is unpacked into the folder in
seconds, at the end. What the installer does print, into the log this module already
keeps, is the truth: a "Downloading <name> from <url>" line per archive (Chromium, then
FFMPEG), then a line per tenth, "|...|  40% of 151.2 MiB". So `percent` is the megabytes
those lines say arrived over the megabytes they say there are, summed over the archives
named so far, and never 100 before the browser is there. Where the log names no size (the
package is still being fetched, or a downloader that prints something else), `percent` is
None and the sentence says what is known, "Getting the installer." or "Downloading
Chromium": never a number made up. An archive at 100% that the installer has not yet
reported as downloaded is being unpacked, and is said so.

Nothing here is a second store: the folder, the log the tool wrote and whether its process
is alive are read each time. Nothing here launches a browser.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from keel import browser, childenv, prereqs
from keel.setupconfig import SetupError

NODE_MIN = 20
LOG = "install.log"
PID = "install.pid"
EXIT = re.compile(r"^exit (\d+)$")
VERSION = re.compile(r"v?(\d+)\.")
# The pinned Playwright's lines where there is no terminal (`logPolitely`, and
# `getBasicDownloadProgress`: one line per tenth), each naming the archive by its title.
PART = re.compile(r"^Downloading (.+) from \S+$")
STEP = re.compile(r"\|\s*(\d{1,3})% of (\d+(?:\.\d+)?) MiB\s*$")
LANDED = re.compile(r"^(.+) downloaded to \S+")
COLOUR = re.compile(r"\x1b\[[0-9;]*m")
GETTING = "Getting the installer. The download starts in a moment."
NODE_FIX = "Install Node.js 20 or newer (nodejs.org, or on Linux your package manager)."
# its own pid first, then the tool, its exit code on the log's last line, the pid file gone
SCRIPT = 'echo $$ >"$2"; "$0" install >"$1" 2>&1; echo "exit $?" >>"$1"; rm -f "$2"'
PS_SECONDS = 5

_procs: list[subprocess.Popen] = []


def log_path() -> Path:
    return browser.home() / LOG


def pid_path() -> Path:
    return browser.home() / PID


def node() -> dict:
    """`{ok, said}`, and `fix` and `command` when it is missing or too old."""
    path = shutil.which("node")
    miss = {"ok": False, "fix": NODE_FIX, "command": prereqs.mac_only("brew install node")}
    if not path:
        return dict(miss, said="Node.js is not installed on this computer.")
    done = prereqs.run([path, "--version"])
    said = (done.stdout or "").strip().splitlines()[0] if done and done.returncode == 0 and (done.stdout or "").strip() else ""
    found = VERSION.match(said)
    if not found:
        return dict(miss, said="Node.js is installed, but its version could not be read.")
    if int(found.group(1)) < NODE_MIN:
        return dict(miss, said=f"Node.js {said} is installed, and Shipyard's browser needs {NODE_MIN} or newer.")
    return {"ok": True, "said": said}


def is_installer(pid: int) -> bool:
    """Whether process `pid` is a download's shell: alive, and its command line carries the
    script and this folder's pid file. A pid alone proves nothing once it has been reused."""
    try:
        os.kill(pid, 0)
        done = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=PS_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and SCRIPT in done.stdout and str(pid_path()) in done.stdout


# What the browser step asks (`firstrunsteps.browser_state`): `node`, through a name the
# suite's fence replaces, since a state built in a test must not run the real program and
# `node` cannot be fenced by name (tests/fence.py, c-678 review F18).
probe = node


def running() -> bool:
    """Whether a download is in flight. One this process started is asked first, which also
    reaps one that has ended (a child nobody waited for would read as alive for as long as
    the deck runs). Else the pid file, for a download a deck before this one started: it
    counts only when it names the installer (`is_installer`), and a stale one is cleared."""
    _procs[:] = [proc for proc in _procs if proc.poll() is None]
    if _procs:
        return True
    try:
        pid = int(pid_path().read_text().strip())
    except OSError:
        return False
    except ValueError:
        pid = 0
    if pid > 0 and is_installer(pid):
        return True
    try:
        pid_path().unlink()
    except OSError:
        pass
    return False


def log_lines() -> list[str]:
    try:
        text = log_path().read_text(errors="replace")
    except OSError:
        return []
    return [line.strip() for line in COLOUR.sub("", text).splitlines() if line.strip()]


def name_of(title: str) -> str:
    """An archive's name from its title: the words before its version or its build
    ("Chromium 141.0.7390.37 (playwright build v1194)", "FFMPEG playwright build v1011")."""
    words = []
    for word in title.split():
        if word[0].isdigit() or word.startswith("(") or word == "playwright":
            break
        words.append(word)
    return " ".join(words) or title


def progress(lines: list[str]) -> dict:
    """How far the download is, from the installer's own lines (the module's note):
    `{part, percent, received_mb, of_mb, unpacking}`. `part` is the archive named last,
    None before any; `percent` is of everything named so far, None while no size is known.
    An archive named again is one the installer began again, so it counts from its start."""
    parts: dict[str, list] = {}         # name: [percent, MiB, landed], in the order named
    part = None
    for line in lines:
        named, step, landed = PART.match(line), STEP.search(line), LANDED.match(line)
        if named:
            part = name_of(named.group(1))
            parts.pop(part, None)
            parts[part] = [None, None, False]
        elif step and part:
            parts[part][:2] = [min(100, int(step.group(1))), float(step.group(2))]
        elif landed and name_of(landed.group(1)) in parts:
            parts[name_of(landed.group(1))][2] = True
    sized = [(percent, size) for percent, size, _ in parts.values() if size]
    total = sum(size for _, size in sized)
    got = sum(size * percent / 100 for percent, size in sized)
    now = parts.get(part) or [None, None, False]
    return {"part": part, "percent": min(99, round(got * 100 / total)) if total else None,
            "received_mb": int(got), "of_mb": int(total) if total else None,
            "part_percent": now[0], "part_mb": now[1], "unpacking": now[0] == 100 and not now[2]}


def said_of(found: dict) -> str:
    """The downloading row's sentence: what is known, and nothing that is not."""
    if found["part"] is None:
        return GETTING
    if found["unpacking"]:
        return f"Unpacking {found['part']}"
    if found["part_percent"] is None:
        return f"Downloading {found['part']}"
    return f"Downloading {found['part']}: {found['part_percent']}% of {found['part_mb']:g} MiB"


def last_said(lines: list[str]) -> tuple[int | None, str]:
    """`(exit code, the tool's last line)` from the log; `(None, "")` with no finished run."""
    if not lines or not EXIT.match(lines[-1]):
        return None, ""
    said = lines[-2] if len(lines) > 1 else ""
    return int(EXIT.match(lines[-1]).group(1)), re.sub(r"^keel-browser:\s*", "", said)


def status(cfg=None) -> dict:
    found = presence()
    out = {"state": "waiting", "percent": 0, "received_mb": 0, "of_mb": None, "part": None, "said": ""}
    if running():
        far = progress(log_lines())
        return dict(out, state="downloading", percent=far["percent"], received_mb=far["received_mb"],
                    of_mb=far["of_mb"], part=far["part"], said=said_of(far))
    if found:
        return dict(out, state="ready", percent=100, said="Shipyard's browser is installed.")
    lines = log_lines()
    code, said = last_said(lines)
    if code is None:
        return out
    far = progress(lines[:-1])
    reached = (f" {far['part']} had reached {far['part_percent']}% of {far['part_mb']:g} MiB."
               if far["part_percent"] is not None else "")
    return dict(out, state="failed", percent=far["percent"], received_mb=far["received_mb"], of_mb=far["of_mb"],
                part=far["part"],
                said=f"The download stopped: {(said or f'the installer exited {code}').rstrip('.')}.{reached}")


def presence() -> bool:
    """Whether the package and a Chromium build are in the browser's folder."""
    where = browser.home()
    return (where / browser.MODULE).is_dir() and bool(browser.chromium_builds(where))


def start(cfg) -> dict:
    """Start the download, detached, unless one is running or Node cannot run the tool."""
    if running():
        raise SetupError("Shipyard's browser is already downloading")
    found = node()
    if not found["ok"]:
        raise SetupError(f"{found['said']} {found['fix']}")
    tool = Path(cfg.root) / "bin" / "keel-browser"
    where = browser.home()
    where.mkdir(parents=True, exist_ok=True)
    log_path().write_text("")
    try:
        proc = subprocess.Popen(["/bin/sh", "-c", SCRIPT, str(tool), str(log_path()), str(pid_path())],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, env=childenv.own_env())
    except OSError as error:
        raise SetupError(f"the download could not be started: {error}") from None
    _procs.append(proc)         # the pid file is the shell's own to write, before the tool runs
    return {"install": dict(status(cfg), state="downloading", percent=None, said=GETTING),
            "note": "downloading Shipyard's browser"}


def wait() -> None:
    """Wait for the downloads this process started (the suite's, so no test reads early)."""
    while _procs:
        _procs.pop().wait()
