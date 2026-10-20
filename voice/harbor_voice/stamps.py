"""Where a Harbor turn's time goes, stamped as it goes (lane H, H2, 2026-09-24).

WHY THIS EXISTS. On the box that morning a trivial Harbor turn was 5.0 s of wall time
(about 3 s to start `claude`, 1.8 s of model), and yet `keel voice latency` put Harbor's
"transcript to first words" at p50 14.8 s. The transcript had a `said` stamp and an
`answer` stamp and nothing between them, so a turn that spent 60 s on tools, a turn that
waited on the conversation lock and a turn whose board pen was slow all read as one number
called "the model". These records are the stamps between, written by the thread that runs
the turn and read back by `keel/voicelatency.py`:

    harbor-start   the `claude` was started (one-shot), or the sentence went down the
                   kept-alive process's stdin (`warm: true`)
    harbor-model   its answer came back, with the envelope's own count of what it did
    harbor-pen     the board pen finished with the answer (a block drawn, or nothing to do)

THE TOOL COUNT IS THE ENVELOPE'S, NOT A GUESS (H1). `claude -p --output-format json` ends
with one `result` record whose `num_turns` counts the model's own round trips: 1 is an
answer with no tool, and every tool round adds one (`tests/fixtures/harness/turn.json` is a
plain answer at 1; `structured.json` is 2, its one tool being the structured output). The
kept-alive process's `result` record carries the same field. So `tools` is `num_turns - 1`,
and a turn whose envelope has no count records none rather than a zero it cannot vouch for.

BEST EFFORT, LIKE EVERY OTHER WRITE TO THE TRANSCRIPT: a stamp never costs the answer.
"""
from __future__ import annotations

import json
from pathlib import Path

SPAWN = "harbor-start"
MODEL = "harbor-model"
PEN = "harbor-pen"
TIER = "harbor"


def envelope(payload) -> dict:
    """What a `result` record says about the turn it ends: its round trips, the tools that
    implies, and the two durations the harness measured itself. Absent fields are left out."""
    if not isinstance(payload, dict):
        return {}
    out = {}
    rounds = payload.get("num_turns")
    if isinstance(rounds, int) and not isinstance(rounds, bool) and rounds >= 1:
        out["numTurns"] = rounds
        out["tools"] = rounds - 1
    for key, name in (("duration_ms", "durationMs"), ("duration_api_ms", "apiMs")):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[name] = value
    return out


def write(path: Path, turn: str, kind: str, at: float, **fields) -> None:
    """One stamp into the transcript, at the instant it names rather than the instant it is
    written: the turn's thread writes them together once the pen is done."""
    if not turn:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps({"at": at, "turn": turn, "kind": kind, "tier": TIER,
                                     **fields}) + "\n")
    except OSError:
        pass


def record(path: Path, turn: str, clock: dict) -> None:
    """Every stamp `clock` holds, in order. `clock` is filled by whoever ran the turn:
    `spawnAt` (and `warm`), `doneAt` and `envelope`, and `penAt` once the pen has run.
    A turn that failed part way writes the stamps it got as far as."""
    clock = clock or {}
    if clock.get("spawnAt") is not None:
        write(path, turn, SPAWN, clock["spawnAt"], warm=bool(clock.get("warm")),
              **({"retried": True} if clock.get("retried") else {}))
    if clock.get("doneAt") is not None:
        write(path, turn, MODEL, clock["doneAt"], **(clock.get("envelope") or {}))
    # A PEN STAMP ONLY AFTER AN ANSWER: without `doneAt` there was nothing to draw from,
    # and a lone pen stamp would measure nothing.
    if clock.get("penAt") is not None and clock.get("doneAt") is not None:
        write(path, turn, PEN, clock["penAt"])
