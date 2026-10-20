"""One file replaced in one rename: a temporary beside it, flushed, fsynced, renamed over.

A reader sees the old file or the new one, never part of either. Used where a file Keel
rewrites is read by another process at the same moment (`keel/claudejson.py` has the
account of why that matters), and for the talker's small state files.
"""

import os
import tempfile
from pathlib import Path


def write_text(path: Path, text: str, mode: int | None = None) -> None:
    """Replace `path` with `text`; `mode` is applied before the rename, so the file is never
    visible with looser permissions than asked for."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if mode is not None:
                os.fchmod(handle.fileno(), mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
