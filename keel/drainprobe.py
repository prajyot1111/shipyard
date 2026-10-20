"""Which Keel drains run as this user on this machine (c-620 review).

Two drains on one machine start houses in the same Claude config dir, each blind to the
other's. So `shipyard import` and `shipyard service install|start` refuse while another one
runs, and the doctor of an install says so. A drain is found two ways, both as the harness
of this machine reports it, never guessed:

- a process: `bin/keel` or `bin/shipyard` running `drain`, or `run` with `drain` among its
  roles (the default), its `KEEL_CONFIG` read from its environment (`/proc/<pid>/environ`,
  else `ps eww`), so this install's own drain is told from another's;
- a service: a loaded launchd agent or an active systemd user unit of an old drain's label
  (`dev.keel`, the old engine; `dev.harbor.worker`; any `dev.keel*` or `dev.harbor.*` label
  naming a drain), or this install's `dev.shipyard.drain`.

Each line names the pid or the label and the command that stops it. Nothing here stops
anything: unloading an old agent is the human's step. docs/atlas/87-import.md.

The fetch role is found the same way (`fetching`, c-742), as a process only: `fetch` as the
loop (never `--once` or `--preview`, which end, nor `--segment`, which is one segment's), or `run` with `fetch` among its roles, with
this install's `KEEL_CONFIG`. The doctor of an install says when none runs while segments
wait on it (docs/atlas/70-segments-and-fetch.md).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

OLD_LABELS = ("dev.keel", "dev.harbor.worker")
OLD_FAMILIES = ("dev.keel", "dev.harbor.")
OWN_LABEL = "dev.shipyard.drain"
DRAIN = re.compile(r"\bbin/(?:keel|shipyard)\s+(run|drain)\b(.*)")
FETCH = re.compile(r"\bbin/(?:keel|shipyard)\s+(run|fetch)\b(.*)")
# Not the install's role: a run that ends, or a loop narrowed to one segment, which leaves the
# other segments unfetched and files no recurring card (r2.F4).
NOT_THE_ROLE = re.compile(r"(?:^|\s)--(?:once|preview|segment)\b")
ROLES = re.compile(r"--roles[= ](\S+)")
CONFIG = re.compile(r"(?:^|\s)KEEL_CONFIG=(\S+)")


def run(*argv: str) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def processes() -> list[tuple[int, str]]:
    """`(pid, command line)` of every process of this user."""
    out = []
    for line in run("ps", "-U", str(os.getuid()), "-o", "pid=,command=").splitlines():
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit():
            out.append((int(pid), args.strip()))
    return out


def is_drain(args: str) -> bool:
    found = DRAIN.search(args)
    if not found:
        return False
    roles = ROLES.search(found.group(2))
    return found.group(1) == "drain" or roles is None or "drain" in roles.group(1).split(",")


def is_fetch(args: str) -> bool:
    """The install's fetch role as a loop: `fetch` that is neither a one-shot nor narrowed to
    one segment (`NOT_THE_ROLE`), or `run` naming the role (`run` alone is the drain)."""
    found = FETCH.search(args)
    if not found:
        return False
    if found.group(1) == "fetch":
        return not NOT_THE_ROLE.search(found.group(2))
    roles = ROLES.search(found.group(2))
    return roles is not None and "fetch" in roles.group(1).split(",")


def config_of(pid: int) -> str | None:
    """The `KEEL_CONFIG` a process runs with, or None when it has none (or it cannot be read)."""
    try:
        environ = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        return next((item[len(b"KEEL_CONFIG="):].decode() for item in environ
                     if item.startswith(b"KEEL_CONFIG=")), None)
    except OSError:
        found = CONFIG.search(run("ps", "eww", "-o", "command=", "-p", str(pid)))
        return found.group(1) if found else None


def labels() -> list[str]:
    """Every loaded launchd agent, or every active systemd user service, by label."""
    if sys.platform == "darwin":
        rows = [line.split("\t") for line in run("launchctl", "list").splitlines()[1:]]
        return [row[2].strip() for row in rows if len(row) == 3]
    out = run("systemctl", "--user", "list-units", "--type=service", "--state=active",
              "--no-legend", "--plain")
    return [line.split()[0].removesuffix(".service") for line in out.splitlines() if line.strip()]


def stop_command(label: str) -> str:
    if sys.platform == "darwin":
        return f"launchctl bootout gui/{os.getuid()}/{label}"
    return f"systemctl --user disable --now {label}.service"


def old_label(label: str) -> bool:
    return label in OLD_LABELS or (label.startswith(OLD_FAMILIES) and "drain" in label)


def same(path: str | None, config: Path) -> bool:
    return bool(path) and Path(path).expanduser().resolve() == Path(config).resolve()


def drains(config: Path) -> tuple[list[str], list[str]]:
    """`(others, ours)`: a line for every drain that is not this install's, with the command
    that stops it, and a plain line for each of this install's own."""
    others, ours = [], []
    for pid, args in processes():
        if pid == os.getpid() or not is_drain(args):
            continue
        where = config_of(pid)
        if same(where, config):
            ours.append(f"running as pid {pid}")
        else:
            others.append(f"pid {pid} ({args[:100]}; KEEL_CONFIG {where or 'unset'}): "
                          f"stop it with `kill {pid}`")
    for label in labels():
        if old_label(label):
            others.append(f"service {label}: unload it with `{stop_command(label)}`")
        elif label == OWN_LABEL:
            ours.append(f"service {label} loaded")
    return others, ours


def fetch_pids(config: Path) -> list[int]:
    """Every other process running the fetch role for this install. `shipyard service` and
    the drain's bring-up read it so a second role is never started beside one (r1.F3)."""
    return [pid for pid, args in processes()
            if pid != os.getpid() and is_fetch(args) and same(config_of(pid), config)]


def fetching(config: Path) -> list[str]:
    """A line for every process running the fetch role for this install; none means nothing
    runs its segments' fetchers."""
    return [f"running as pid {pid}" for pid in fetch_pids(config)]


def refusal(config: Path) -> str | None:
    """Why another drain makes a second one unsafe here, or None."""
    others, _ = drains(config)
    if not others:
        return None
    return ("another Shipyard drain runs as this user on this machine, and two drains must not "
            "share its houses: " + "; ".join(others))
