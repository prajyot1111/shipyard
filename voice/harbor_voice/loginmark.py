"""The gateway's half of the Logins list (c-558, `keel/logins.py`): a key the far end
refused marks its row at once, so the deck turns amber on the turn that failed rather than
when somebody next checks, and a call that succeeds takes a mark off again.

Only the row's id and why travel; the key never does. The file is the gateway's own state
dir's (`config.STATE`), never one a config would have to find, so the selftest's scratch
home is all it can touch. At most one mark per row a minute, because a refused key fails
every call until it is fixed. A success looks at the file's modification time, one `stat`,
and reads it only when it changed since this row last looked (a refused fetch's mark, one
from before this gateway started, one this process wrote): the drain's presence check
cannot take a key's mark off, since a key that is there can still be refused.
"""

import sys
import threading
import time
from pathlib import Path

# The code that marks is the code this gateway runs (`drawing.py` says why).
CHECKOUT = Path(__file__).resolve().parents[2]
if str(CHECKOUT) not in sys.path:
    sys.path.append(str(CHECKOUT))

from harbor_voice import config                                          # noqa: E402

EVERY = 60.0
REFUSED = (401, 403)
_last: dict[str, float] = {}      # a refusal marked from here, by row, when
_seen: dict[str, int | None] = {}  # the file's mtime when each row last looked
_lock = threading.Lock()


def _file() -> Path:
    return Path(config.STATE) / "logins.json"


def _mtime() -> int | None:
    try:
        return _file().stat().st_mtime_ns
    except OSError:
        return None


def works(row_id: str) -> bool:
    """A call succeeded: the row's mark comes off, when the file changed since this row
    last looked. True when it looked; a failed look is tried again on the next success."""
    now = _mtime()
    with _lock:
        if row_id in _seen and _seen[row_id] == now:
            return False
    try:
        from keel import logins
        done = logins.unmark_at(config.STATE, row_id)
    except Exception:                                                   # noqa: BLE001
        done = False
    if done:
        with _lock:
            _seen[row_id] = _mtime()
            _last.pop(row_id, None)
    return done


def refused(row_id: str, why: str) -> bool:
    """Mark `row_id` expired with `why`; False when it was marked under a minute ago or the
    mark could not be written. Never raises: the caller is on its own failure path."""
    now = time.monotonic()
    with _lock:
        if now - _last.get(row_id, -EVERY) < EVERY:
            return False
        _last[row_id] = now
    try:
        from keel import logins
        return logins.mark_at(config.STATE, row_id, why)
    except Exception:                                                   # noqa: BLE001
        return False
