"""How much memory a live house holds: the resident size of its process tree (c-607).

The house is the pid the harness lists for its session (`claude agents --json`, the row's
`pid`), and everything under it by parent pid: its tools, its MCP servers, its background
shells. Their resident sizes (RSS) are summed. It is read on the machine the house runs on,
with the live strip's facts (`keel/livestrip.py`), and held in memory with them: never on
the board. A row with no `pid` has no reading, never a guess.

Two ways to read the process table, the standard library only:

- **Linux**: `/proc/<pid>/stat` for the parent pid (the field after the command, which is
  in parentheses and may hold spaces or a `)`), `/proc/<pid>/statm` for the resident pages.
- **macOS** (where the work houses run): one `ps -A -o pid=,ppid=,rss=`, RSS in KiB.

One table is read per strip read, however many houses it serves. The sum is rounded to
`STEP_MB`, so a house whose size wobbles by a few megabytes between two reads is not news
on the event stream every three seconds (`livestrip.same`).
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PROC = Path("/proc")
PS = ("ps", "-A", "-o", "pid=,ppid=,rss=")
PS_SECONDS = 5
STEP_MB = 50
# One read of the table serves every caller within this long (c-607 review): the box's watcher
# and a state build both read the strip every few seconds, and the scan is the same answer.
CACHE_SECONDS = 2.0
_cache: dict = {"at": float("-inf"), "table": {}}
_cache_lock = threading.Lock()


def parse_ps(text: str) -> dict[int, tuple[int, int]]:
    """`{pid: (ppid, rss KiB)}` from `ps -A -o pid=,ppid=,rss=` (macOS and Linux alike)."""
    table = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            pid, ppid, rss = (int(part) for part in parts)
        except ValueError:
            continue
        table[pid] = (ppid, rss)
    return table


def parse_stat_ppid(text: str) -> int | None:
    """The parent pid from a `/proc/<pid>/stat` line: the second field after the command's
    closing parenthesis, found from the right, since the command may hold one."""
    close = (text or "").rfind(")")
    fields = text[close + 1:].split() if close >= 0 else []
    try:
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def parse_statm_kib(text: str, page_kib: int) -> int | None:
    """Resident KiB from a `/proc/<pid>/statm` line: its second field, in pages."""
    fields = (text or "").split()
    try:
        return int(fields[1]) * page_kib
    except (IndexError, ValueError):
        return None


def proc_table(root: Path = PROC) -> dict[int, tuple[int, int]]:
    """The table from `/proc`. A process that ends while it is read is left out."""
    page_kib = max(1, os.sysconf("SC_PAGE_SIZE") // 1024)
    table = {}
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            ppid = parse_stat_ppid((entry / "stat").read_text())
            rss = parse_statm_kib((entry / "statm").read_text(), page_kib)
        except OSError:
            continue
        if ppid is not None and rss is not None:
            table[int(entry.name)] = (ppid, rss)
    return table


def ps_table(run=subprocess.run) -> dict[int, tuple[int, int]]:
    result = run(list(PS), capture_output=True, text=True, timeout=PS_SECONDS)
    return parse_ps(result.stdout)


def read_table() -> dict[int, tuple[int, int]]:
    try:
        return proc_table() if PROC.is_dir() and sys.platform.startswith("linux") else ps_table()
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def table(clock=time.monotonic) -> dict[int, tuple[int, int]]:
    """This machine's process table, or `{}` when it cannot be read (nothing is drawn); read
    at most once per CACHE_SECONDS whoever asks."""
    with _cache_lock:
        if clock() - _cache["at"] >= CACHE_SECONDS:
            _cache["table"], _cache["at"] = read_table(), clock()
        return _cache["table"]


def as_pid(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def tree_kib(pid, procs: dict[int, tuple[int, int]], extra=()) -> int | None:
    """The summed RSS of `pid` and every process under it, or None when `pid` is not in the
    table (it ended, or the listing named none). `extra` are more roots counted with it once
    each: the house's background jobs by the pid its job record names, which a shell that
    outlived its parent (reparented to pid 1) is no longer under the house's pid."""
    pid = as_pid(pid)
    if pid is None or pid not in procs:
        return None
    children: dict[int, list[int]] = {}
    for one, (ppid, _) in procs.items():
        children.setdefault(ppid, []).append(one)
    roots = [pid] + [p for p in (as_pid(one) for one in extra) if p in procs and p != 1]
    total, todo, seen = 0, roots, set()
    while todo:
        one = todo.pop()
        if one in seen:
            continue
        seen.add(one)
        total += procs[one][1]
        todo.extend(children.get(one, ()))
    return total


def mem_mb(pid, procs: dict[int, tuple[int, int]], extra=()) -> int | None:
    """The tree's RSS in MB, rounded to STEP_MB (at least one step for a live tree)."""
    kib = tree_kib(pid, procs, extra)
    if kib is None:
        return None
    return max(STEP_MB, int(round(kib / 1024 / STEP_MB)) * STEP_MB)
