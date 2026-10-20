"""Keep `state/logs` bounded: a log past its size is copied aside and cut back to its tail.

Every log here is append-only and nothing else ever shortens one: `drain.log` and
`fetch.log` are appended by Keel a line at a time, and `keel.err.log`, `voice.log` and
`talker.log` are the files launchd (or systemd's `append:`) holds open as a service's
stdout and stderr for as long as it runs. A rename would leave such a service writing into
the renamed file, so the file is cut in place instead. Both service managers open it in
append mode, which is what makes that safe: the next write lands at the new end rather
than at the old offset with a hole before it.

One older generation is kept as `<name>.1`, so a log costs at most twice `LOG_MAX_BYTES`.
The newest `TAIL_BYTES` stay in the live file, from a line boundary, so `tail` and the
deck's drain pill (which reads `drain.log`'s last line) never find it empty. A line another
process writes between the copy and the cut is lost; for a log that is the accepted price.
"""

import os
import shutil
from pathlib import Path

LOG_MAX_BYTES = 5 * 1024 * 1024
TAIL_BYTES = 64 * 1024


def tail_of(path: Path, size: int, keep: int) -> bytes:
    """The last `keep` bytes of `path`, starting on a line boundary."""
    with open(path, "rb") as handle:
        handle.seek(max(0, size - keep))
        tail = handle.read()
    if size > keep:
        _, _, tail = tail.partition(b"\n")
    return tail


def trim(logs_dir: Path, max_bytes: int | None = None, keep: int | None = None) -> list[str]:
    """Cut back every `*.log` in `logs_dir` that has passed `max_bytes`; the names it cut."""
    max_bytes = LOG_MAX_BYTES if max_bytes is None else max_bytes
    keep = TAIL_BYTES if keep is None else keep
    cut = []
    for path in sorted(logs_dir.glob("*.log")):
        try:
            size = path.stat().st_size
            if size <= max_bytes:
                continue
            tail = tail_of(path, size, keep)
            shutil.copyfile(path, path.with_name(path.name + ".1"))
            os.truncate(path, 0)
            with open(path, "ab") as handle:
                handle.write(tail)
        except OSError:
            continue      # a log that cannot be cut this pass is tried again on the next
        cut.append(path.name)
    return cut
