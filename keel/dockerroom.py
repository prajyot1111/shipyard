"""`keel doctor`'s Docker line: how much of the Mac Docker Desktop leaves to macOS (c-532).

The Mac's houses do their heavy work in containers, so Docker's memory is their budget
(`[keel] memory_floor_mb = 0`, no host floor). What Docker is given is taken from macOS: on
2026-09-26 it was set to 10 GB of 16 and macOS swapped 6 of 7 GB. So on a macOS host that
serves spaces the doctor reads Docker Desktop's allocation (`MemoryMiB` in its
`settings-store.json`, or `memoryMiB` in the older `settings.json`) against the machine's
memory (`sysctl -n hw.memsize`), and `ROOM_MIB` or less left for macOS is a problem,
which, like every doctor problem, is a sighting for Bosun. Or less, not under: the
incident itself left exactly 6 GB, and a check that let it pass would not be one. It
reads and never resizes. Elsewhere the line reads "not applicable".
"""

import json
import subprocess
import sys
from pathlib import Path

ROOM_MIB = 6 * 1024
SETTINGS = ("Library/Group Containers/group.com.docker/settings-store.json",
            "Library/Group Containers/group.com.docker/settings.json")
KEYS = ("MemoryMiB", "memoryMiB")
SYSCTL_SECONDS = 5
MIB = 1024 * 1024


def applicable(cfg, platform: str | None = None) -> bool:
    """A Mac that runs houses: only there does Docker share the houses' machine with macOS."""
    return (platform or sys.platform) == "darwin" and bool(cfg.served_spaces())


def allocation(home: Path) -> tuple[int | None, str | None]:
    """Docker Desktop's memory in MiB, and the file it was read from; (None, why) when no
    settings file says."""
    for name in SETTINGS:
        path = home / name
        try:
            settings = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for key in KEYS:
            value = settings.get(key) if isinstance(settings, dict) else None
            if isinstance(value, (int, float)) and value > 0:
                return int(value), str(path)
    return None, "no Docker Desktop settings file names its memory"


def machine_mib() -> int | None:
    try:
        shown = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                               timeout=SYSCTL_SECONDS)
        return int(shown.stdout.strip()) // MIB if shown.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def gather(cfg, home: Path | None = None, platform: str | None = None,
           memsize=machine_mib) -> dict:
    if not applicable(cfg, platform):
        return {"applicable": False}
    docker, source = allocation(home or Path.home())
    machine = memsize()
    found = {"applicable": True, "docker_mib": docker, "machine_mib": machine,
             "room_mib": ROOM_MIB, "source": source}
    if docker is not None and machine is not None:
        found["left_mib"] = machine - docker
    return found


def gb(mib: int) -> str:
    return f"{mib / 1024:.1f} GB"


def problem(found: dict) -> str | None:
    left = found.get("left_mib")
    if not found.get("applicable") or left is None or left > found["room_mib"]:
        return None
    return (f"docker: Docker Desktop is given {gb(found['docker_mib'])} of "
            f"{gb(found['machine_mib'])}, leaving macOS {gb(left)}; at {gb(found['room_mib'])} "
            f"or less macOS swaps, so lower Memory in Docker Desktop's Resources settings")


def line(found: dict) -> str:
    if not found.get("applicable"):
        return "docker        not applicable (not macOS)"
    if found.get("left_mib") is None:
        why = found["source"] if found.get("docker_mib") is None else "hw.memsize unreadable"
        return f"docker        unknown ({why})"
    return (f"docker        {gb(found['docker_mib'])} of {gb(found['machine_mib'])}, "
            f"macOS keeps {gb(found['left_mib'])}"
            + ("  LOW" if problem(found) else ""))
