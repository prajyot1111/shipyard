"""What this machine says about itself: available memory, the process table, and nice.

The drain's box limits (`keel/drain.py`) read these and nothing else does. Each is one
read of the operating system, and each answers None rather than raising when the machine
will not say, so the policy that reads it decides what "unknown" means.

- `available_mb`: Linux's `MemAvailable`, or on macOS `vm_stat`'s free, inactive and
  speculative pages, which is what the kernel can hand out without swapping.
- `process_table`: one `ps` snapshot, pid to (parent, resident KB). A house is a process
  tree (the session, its shells, its test runs, its browser), so its memory is the tree's.
- `renice`: raise the nice of a set of pids to at least a value. It never lowers one, which
  an unprivileged process cannot do anyway.
"""

import os
import re
import subprocess
from pathlib import Path

MEMINFO = Path("/proc/meminfo")
VM_PAGE = re.compile(r"page size of (\d+) bytes")
VM_LINE = re.compile(r"^Pages (free|inactive|speculative):\s+(\d+)\.", re.MULTILINE)
PS_ARGV = ["ps", "-A", "-o", "pid=,ppid=,rss="]
TIMEOUT = 10


def available_mb() -> int | None:
    """Memory the machine can give a new process without swapping, in MB; None when unread."""
    if MEMINFO.exists():
        return meminfo_available(MEMINFO.read_text())
    try:
        result = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return vm_stat_available(result.stdout) if result.returncode == 0 else None


def meminfo_available(text: str) -> int | None:
    match = re.search(r"^MemAvailable:\s+(\d+) kB", text, re.MULTILINE)
    return int(match.group(1)) // 1024 if match else None


def vm_stat_available(text: str) -> int | None:
    page = VM_PAGE.search(text)
    pages = VM_LINE.findall(text)
    if not page or not pages:
        return None
    return sum(int(count) for _, count in pages) * int(page.group(1)) // (1024 * 1024)


def process_table() -> dict[int, tuple[int, int]] | None:
    """pid to (parent pid, resident KB), from one `ps`; None when `ps` will not answer."""
    try:
        result = subprocess.run(PS_ARGV, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_ps(result.stdout) if result.returncode == 0 else None


def parse_ps(text: str) -> dict[int, tuple[int, int]]:
    table = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            table[int(parts[0])] = (int(parts[1]), int(parts[2]))
    return table


def tree(table: dict[int, tuple[int, int]], root: int) -> list[int]:
    """`root` and every descendant it has in the table; empty when `root` is not there."""
    if root not in table:
        return []
    children: dict[int, list[int]] = {}
    for pid, (parent, _) in table.items():
        children.setdefault(parent, []).append(pid)
    found, stack = [], [root]
    while stack:
        pid = stack.pop()
        if pid in found:
            continue
        found.append(pid)
        stack.extend(children.get(pid, []))
    return found


def tree_mb(table: dict[int, tuple[int, int]], root: int) -> int:
    """The resident memory of `root`'s whole tree, in MB."""
    return sum(table[pid][1] for pid in tree(table, root)) // 1024


def renice(pids: list[int], nice: int) -> int:
    """Raise each pid's nice to `nice` where it is lower; how many moved. A pid that is
    gone, or not ours, is passed over."""
    moved = 0
    for pid in pids:
        try:
            if os.getpriority(os.PRIO_PROCESS, pid) < nice:
                os.setpriority(os.PRIO_PROCESS, pid, nice)
                moved += 1
        except OSError:
            continue
    return moved
