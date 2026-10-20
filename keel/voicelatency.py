"""`keel voice latency`: where a voice turn's time goes, per stage, from the transcript.

READ ONLY, AND FROM WHAT IS ALREADY WRITTEN (D-5). Every figure here is the difference
between two `at` stamps the gateway already writes to `state/voice/transcript.jsonl`, so
each speed change is measured on his real turns rather than on a probe. Nothing is
written, nothing is called, and a record this cannot read is skipped.

THE STAGES, and the records that bound each one:

    end        the listen ended: an `endpoint` record (hands-free, the detector) or the
               page's `release` trace (push to talk), whichever came last before the turn
    stt        end -> the turn's `said` record: the page's `end`, the speech model and
               the hearing repair
    model      `said` -> the first `answer-part` (a streamed answer) or else the `answer`
               record: the turn's first words from the model
    tts        first words -> `first-audio`, the first synthesised chunk sent to the page
               (written since D-5; older turns show no tts stage)
    total      end -> first audio, what he actually waits

A turn with no end record (a typed turn, or a listen ended by a message this does not
know) has no stt and no total; its model stage is still counted.

HARBOR'S TURN, SPLIT (lane H, H2, 2026-09-24). The model stage above is everything between
his words and Harbor's, and on the box it read p50 14.8 s for a turn that measured 5 s by
hand. Harbor's thread now stamps what happened in between (`voice/harbor_voice/stamps.py`),
and each gap is its own stage:

    wait       `said` -> `harbor-start`: the conversation lock, the session, the framing
    run        `harbor-start` -> `harbor-model`: the `claude` process, start, model and tools
    pen        `harbor-model` -> `harbor-pen`: the board pen on the finished answer
    deliver    `harbor-model` -> the `answer` record: the pen, the inbox and the watch loop

`harbor-model` carries the envelope's tool count, so each tier that has one is also
reported twice more, as "<tier>, tool-free" and "<tier>, with tools": a turn that grepped
the Atlas for a minute is not the same measurement as one that answered from the digest.
A turn from before the stamps has none of these and is counted in neither half.
"""
from __future__ import annotations

import json
from pathlib import Path

# An end record further back than this from a turn belongs to an earlier listen.
END_WINDOW = 30.0
HOUSE = "house"
STAGES = ("stt", "model", "wait", "run", "pen", "deliver", "tts", "total")
# Printed only where some turn has them: an instant answer or a capture never stamps these.
HARBOR_STAGES = ("wait", "run", "pen", "deliver")
LABELS = {"stt": "end to transcript", "model": "transcript to first words",
          "wait": "transcript to spawn", "run": "spawn to model done",
          "pen": "board pen", "deliver": "model done to answer",
          "tts": "first words to first audio", "total": "end to first audio"}
# The stamp record kinds and the row field each one fills (`harbor_voice/stamps.py`).
STAMPS = {"harbor-start": "spawn", "harbor-model": "done", "harbor-pen": "penned"}


def read(path: Path) -> list[dict]:
    """Every record that parses, in file order. A missing file is no records."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("at"), (int, float)):
            rows.append(rec)
    return rows


def is_end(rec: dict) -> bool:
    if rec.get("kind") == "endpoint" and rec.get("reason") == "hangover":
        return True
    return rec.get("kind") == "page" and rec.get("event") == "release"


def tier_of(current: str, rec: dict) -> str:
    """The turn's tier after one more of its records (H3). A turn that went to a house is
    the house's for good: a `connected` record or a `house` tier outranks any label a later
    record carries, so a house turn is never counted as Harbor's time."""
    if current == HOUSE or rec.get("kind") == "connected" or rec.get("tier") == HOUSE:
        return HOUSE
    return str(rec.get("tier") or current)


def turns(records: list[dict]) -> list[dict]:
    """One row per turn that was said: its tier and the stamps each stage is cut from."""
    out: dict[str, dict] = {}
    last_end = None
    for rec in records:
        if is_end(rec):
            last_end = rec["at"]
            continue
        turn = str(rec.get("turn") or "")
        kind = rec.get("kind")
        if not turn:
            continue
        if kind == "said" and turn not in out:
            end = last_end if last_end is not None and 0 <= rec["at"] - last_end <= END_WINDOW else None
            out[turn] = {"turn": turn, "tier": rec.get("tier") or "", "said": rec["at"],
                         "end": end, "words": None, "audio": None, "answer": None,
                         "spawn": None, "done": None, "penned": None, "tools": None}
            last_end = None
            continue
        row = out.get(turn)
        if row is None:
            continue
        row["tier"] = tier_of(row["tier"], rec)
        if kind == "answer" and row["answer"] is None:
            row["answer"] = rec["at"]
        if kind == "answer-part" and row["words"] is None:
            row["words"] = rec["at"]
        elif kind == "answer" and row["words"] is None and rec.get("spoken") is not False:
            row["words"] = rec["at"]
        elif kind == "first-audio" and row["audio"] is None:
            row["audio"] = rec["at"]
        elif kind in STAMPS and row[STAMPS[kind]] is None:
            row[STAMPS[kind]] = rec["at"]
            if kind == "harbor-model" and isinstance(rec.get("tools"), int):
                row["tools"] = rec["tools"]
    return [stages(row) for row in out.values()]


def stages(row: dict) -> dict:
    """The row with each stage's seconds, or None where a bound is missing."""
    def span(a, b):
        return round(b - a, 3) if a is not None and b is not None and b >= a else None
    return {**row, "stt": span(row["end"], row["said"]), "model": span(row["said"], row["words"]),
            "wait": span(row["said"], row["spawn"]), "run": span(row["spawn"], row["done"]),
            "pen": span(row["done"], row["penned"]), "deliver": span(row["done"], row["answer"]),
            "tts": span(row["words"], row["audio"]), "total": span(row["end"], row["audio"])}


def percentile(values: list[float], share: float) -> float | None:
    """Nearest rank: the smallest value with at least `share` of the values at or below."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * share // 1))
    return ordered[int(rank) - 1]


def group(rows: list[dict]) -> dict:
    """One group's count and, per stage, how many turns had it, p50 and p95 in seconds."""
    out: dict = {"turns": len(rows)}
    for stage in STAGES:
        values = [row[stage] for row in rows if row[stage] is not None]
        out[stage] = {"n": len(values), "p50": percentile(values, 0.5),
                      "p95": percentile(values, 0.95)}
    return out


def summary(rows: list[dict]) -> dict:
    """Per tier, then that tier's tool-free and with-tools halves where it has a count."""
    tiers: dict[str, dict] = {}
    for tier in sorted({row["tier"] or "?" for row in rows}):
        mine = [row for row in rows if (row["tier"] or "?") == tier]
        tiers[tier] = group(mine)
        counted = [row for row in mine if row.get("tools") is not None]
        if counted:
            tiers[f"{tier}, tool-free"] = group([r for r in counted if r["tools"] == 0])
            tiers[f"{tier}, with tools"] = group([r for r in counted if r["tools"] > 0])
    return tiers


def lines(tiers: dict) -> list[str]:
    if not tiers:
        return ["no turns in the transcript"]
    out = []
    for tier, row in tiers.items():
        out.append(f"{tier}: {row['turns']} turn(s)")
        for stage in STAGES:
            cell = row[stage]
            if not cell["n"] and stage in HARBOR_STAGES:
                continue
            if not cell["n"]:
                out.append(f"  {LABELS[stage]:<28} no data")
                continue
            out.append(f"  {LABELS[stage]:<28} p50 {cell['p50']:.2f}s  p95 {cell['p95']:.2f}s  "
                       f"(n={cell['n']})")
    return out


def report(path: Path, last: int = 0) -> dict:
    """The whole report for one transcript: the per-tier summary and the turns it read."""
    rows = turns(read(path))
    if last > 0:
        rows = rows[-last:]
    return {"transcript": str(path), "tiers": summary(rows), "turns": rows}
