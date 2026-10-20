"""The state bus: one writer, many readers, and no way in.

Reimplemented from the contract in `artifacts/fsa-review/findings.md` section 5, which is
the cleanest thing in the four repositories reviewed there. Not a copied line of AGPL
source: this is about twenty lines written from a written-down contract, which is why the
licence question in that review does not arrive with it.

    GET /voice/state -> {"state", "level", "samples", "alert", "loading", "turn",
                         "narration"}

TWO DERIVED RULES ARE KEPT EXACTLY, because they are what makes any face built against
ai-visualizer run against this unmodified:

    a waveform younger than 0.6 s OVERRIDES the state word to "speaking"
    level = min(1.0, mean(abs(samples)) / 3000)

EXACTLY ONE PROCESS WRITES THIS, AND THERE IS NO POST ANYWHERE. Harbor does not write the
bus. Harbor writes `keel-voice say`, which lands in a separate inbox directory and is
an INPUT to the gateway. Keeping those two apart is what stops the bus having two
writers, which is the fault the original grew a self-heal against.

ONE FIELD THE ORIGINAL COULD NOT CARRY: `turn.tier`. Their bus is a global singleton with
no session identity, because it supervises one agent. Harbor supervises many, so the turn
says which tier is answering. `core.js` ignores unknown fields, so this stays additive
and a face written for the original still runs.

THE FILE MIRROR is for any face that reads the file bus rather than an endpoint. Four
files, the original's names, written best-effort: a bus that can crash the voice line is
worse than no bus, so every write here is wrapped and every failure is dropped.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from . import config

STATES = ("idle", "listening", "thinking", "speaking")

# The original's four file names, so `bus_dir` can be pointed at our data/ directory and
# an unmodified visualizer performs.
F_STATE = ".voice_state"
F_WAVE = ".voice_waveform"
F_ALERT = ".voice_alert"
F_LOADING = ".voice_loading_pid"


def level_of(samples) -> float:
    """min(1.0, mean(|samples|) / 3000), int16 scale. The contract's formula, unchanged."""
    if not samples:
        return 0.0
    return min(1.0, sum(abs(float(s)) for s in samples) / len(samples)
               / config.BUS_LEVEL_DIVISOR)


class Bus:
    """The whole published state of the voice front end. Read by the page, by the card,
    and by anything else that wants it. Written here and nowhere else."""

    def __init__(self, data_dir: Path | None = None, mirror: bool = True):
        self.dir = Path(data_dir or config.DATA)
        self.mirror = mirror
        self._lock = threading.Lock()
        self._state = "idle"
        self._samples: list[float] = []
        self._wave_at = 0.0
        self._alert = False
        self._loading = False
        self._turn: dict = {}
        self._narration = ""
        self._speech = ""          # which TTS actually answered, so a degraded voice shows
        # WHICH CARD HE IS CONNECTED TO (V4), or None. The page names it in the header
        # while it is set, so what he is talking to is readable without asking.
        self._connected: dict | None = None
        self._last_write = 0.0

    # -- reading, in process ------------------------------------------------ #

    @property
    def state(self) -> str:
        """The bare state word, without the waveform freshness `read` layers on top.

        IN MEMORY AND NOT THROUGH `read`, because the end-of-utterance detector asks this
        once per audio frame to decide whether to listen at all (server.py). `read`
        composes a whole document and takes the lock; this is an attribute. The detector
        must never be the reason a real-time path got slower.

        THE RAW WORD IS ALSO THE RIGHT ONE HERE. `read` reports "speaking" whenever a
        waveform is fresh, which is true while HE is talking too, since the page feeds
        its own levels in. Gating the detector on that would mean it stopped listening
        exactly when he started, so this reads what `set_state` was actually told.
        """
        return self._state

    # -- writing ----------------------------------------------------------- #

    def set_state(self, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"not a bus state: {state!r}")
        with self._lock:
            self._state = state
        self._publish()

    def feed_waveform(self, samples) -> None:
        """Throttled to BUS_HZ, downsampled to 64 points, int16 scale.

        The throttle is here rather than at the caller because the caller is an audio
        loop: it produces frames far faster than anything reads them, and a bus write per
        frame is how a display concern gets into a real-time path.
        """
        now = time.time()
        with self._lock:
            if now - self._last_write < 1.0 / config.BUS_HZ:
                return
            self._last_write = now
            self._samples = downsample(samples, config.BUS_SAMPLES)
            self._wave_at = now
        self._publish()

    def set_alert(self, alert: bool) -> None:
        with self._lock:
            self._alert = bool(alert)
        self._publish()

    def set_loading(self, loading: bool) -> None:
        with self._lock:
            self._loading = bool(loading)
        self._publish()

    def set_turn(self, turn: dict | None) -> None:
        with self._lock:
            self._turn = dict(turn or {})
        self._publish()

    def set_narration(self, line: str) -> None:
        with self._lock:
            self._narration = str(line or "")
        self._publish()

    def set_speech(self, name: str) -> None:
        with self._lock:
            self._speech = str(name or "")

    def set_connected(self, connected: dict | None) -> None:
        """The card voice is pinned to, or None. Published like every other state word,
        so a page that opens mid-conversation reads it and draws the header correctly."""
        with self._lock:
            self._connected = dict(connected) if connected else None
        self._publish()

    # -- reading ----------------------------------------------------------- #

    def read(self) -> dict:
        """What GET /voice/state answers. The override rule lives here, in the reader,
        exactly as it does in the original: the writer never has to remember it."""
        with self._lock:
            fresh = (time.time() - self._wave_at) < config.BUS_WAVE_FRESH
            state = "speaking" if (fresh and self._state != "listening") else self._state
            samples = list(self._samples) if fresh else []
            return {
                "state": state,
                "level": level_of(samples),
                "samples": samples,
                "alert": self._alert,
                "loading": self._loading,
                "turn": dict(self._turn),
                "narration": self._narration,
                "speech": self._speech,
                "connected": dict(self._connected) if self._connected else None,
            }

    # -- the file mirror ---------------------------------------------------- #

    def _publish(self) -> None:
        if not self.mirror:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            snap = self.read()
            _atomic(self.dir / F_STATE, snap["state"])
            _atomic(self.dir / F_WAVE,
                    json.dumps({"ts": time.time(), "samples": snap["samples"]}))
            _atomic(self.dir / F_ALERT, "1" if snap["alert"] else "")
            if snap["loading"]:
                _atomic(self.dir / F_LOADING, str(os.getpid()))
            else:
                (self.dir / F_LOADING).unlink(missing_ok=True)
        except Exception:                                               # noqa: BLE001
            # A bus that can crash the voice line is worse than no bus. Same rule the
            # original states about its own writes, and the same reason.
            pass


def _atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def downsample(samples, n: int) -> list[float]:
    """n points out of however many arrived, by taking the peak of each bucket.

    The PEAK rather than the mean, because a mean of a bipolar audio buffer trends to
    zero and draws a flat line while somebody is talking. The original downsamples to 64
    for the same display reason.
    """
    xs = [float(s) for s in samples]
    if not xs:
        return []
    if len(xs) <= n:
        return xs + [0.0] * (n - len(xs))
    size = len(xs) / n
    out = []
    for i in range(n):
        chunk = xs[int(i * size):max(int((i + 1) * size), int(i * size) + 1)]
        out.append(max(chunk, key=abs) if chunk else 0.0)
    return out
