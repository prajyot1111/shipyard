"""The judges' switch and their shadow report: Keel's half.

A judge is a named decision point with a typed verdict and two implementations behind one
call, the RULE (what decides today) and JEV. The judges themselves live in the gateway
(`voice/harbor_voice/judges.py`), because that is the only process that asks one. This
module is what Keel's side needs: the switch, and the report that is the evidence for a
flip.

THE SWITCH HAS TWO HALVES, and that is his call of 2026-09-20, not an accident.

- `[voice.judges]` in the install's `config.toml` holds the SHIPPED DEFAULTS, all `shadow`. It is one
  config line for a permanent change, which is what V10 asked for.
- `state/voice/judges.json` holds the LIVE OVERRIDE, and only `keel voice judge` writes
  it. The effective mode is the override if there is one, else the default.

The reason the live value is not in the config is mechanical, and dates from when the config
was the tracked `keel.toml`: that file was tracked, the
box's `~/keel` is the canonical checkout, the Mac pushes to it with
`receive.denyCurrentBranch=updateInstead`, which REFUSES a dirty tree, and a tracked file
is never left modified on either main checkout. A verb that rewrote `keel.toml` in place
would either block every push from the Mac or have to make commits on `main` from a CLI
verb, differently on each machine. An override file under `state/` has neither problem, is
written by a temp file and a rename, and is not in any backup set's way.

FAIL SAFE, not fail convenient. A key with no default anywhere reads `off`, not `shadow`:
the fallback must never be the one that starts sending his transcripts to a third party.
A key whose mode is `on` but has no confidence floor also reads `shadow`, because `on`
without a floor has no defined meaning. `keel voice judge <key> on` refuses to write that
in the first place; this is the second line of defence, for a hand-edited file.

Every flip is appended to `state/voice/judges.jsonl` as its own line. V10 says a judge goes
`on` when he has read the report and says so, and now that saying so is not a commit, the
line is the record that it happened.

`keel/voice.py` routes `keel voice judge` and `keel voice judges` here. The gateway reads
the same two files for itself (it cannot import this package: different interpreter), so
`voice/harbor_voice/fixtures/judges_switch.json` is read by both suites and is the one
place the format is pinned.
"""

import json
import os
import socket
import time
import tomllib
from pathlib import Path

# V10's keys: one per judge per answer where it matters. The set is the code's, not
# the file's, so a typo in the config is a key nobody reads rather than a fifth judge. The
# last four are c-542's ranked seats (c-552), answers on the one `preturn` call.
KEYS = ("preturn.complete", "preturn.addressed", "preturn.route", "narrate",
        "preturn.card", "preturn.prefetch", "preturn.repair", "preturn.bargein")
MODES = ("off", "shadow", "on")
FALLBACK = "off"                 # a key nothing names: silent, never shadow
SWITCH_FILE = "judges.json"      # under state/voice/
LOG_FILE = "judges.jsonl"        # under state/voice/
TRANSCRIPT_FILE = "transcript.jsonl"   # under state/voice/, the gateway's turn record
DEFAULT_TABLE = "judges"         # [voice.judges]
FLOOR_TABLE = "judge_floors"     # [voice.judge_floors]


class SwitchError(ValueError):
    """A mode or a key that is not one of the sets above."""


# ----- reading the two halves -----

def defaults(toml_path: Path) -> dict[str, str]:
    """`[voice.judges]` from the config: the shipped mode per key."""
    return _table(toml_path, DEFAULT_TABLE)


def floors(toml_path: Path) -> dict[str, float]:
    """`[voice.judge_floors]`: the confidence a judge's answer must clear to decide.

    Empty as shipped, and deliberately: no floor is set until B0's number is on the card
    and a week of the shadow report has been read (V10)."""
    table = _table(toml_path, FLOOR_TABLE)
    out = {}
    for key, value in table.items():
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _table(toml_path: Path, name: str) -> dict:
    """One sub-table of `[voice]`, keys restricted to `KEYS`, or empty on any trouble.

    A malformed or missing config is not a reason to raise here: every caller is
    either a report or a mode lookup, and both want an answer."""
    try:
        with open(toml_path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    table = (data.get("voice") or {}).get(name) or {}
    return {key: table[key] for key in KEYS if key in table}


def overrides(state_dir: Path) -> dict[str, str]:
    """`state/voice/judges.json`: only the keys he has flipped by hand."""
    try:
        data = json.loads((state_dir / "voice" / SWITCH_FILE).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: str(data[key]) for key in KEYS
            if key in data and str(data[key]) in MODES}


def effective(toml_path: Path, state_dir: Path) -> dict[str, dict]:
    """The one answer per key: its mode, where it came from, and its floor.

    `{key: {"mode": ..., "from": "default"|"override"|"fallback", "floor": float|None}}`,
    every key of `KEYS` present, so no reader has to know the set."""
    shipped, live, bars = defaults(toml_path), overrides(state_dir), floors(toml_path)
    out = {}
    for key in KEYS:
        if key in live:
            mode, source = live[key], "override"
        elif str(shipped.get(key)) in MODES:
            mode, source = str(shipped[key]), "default"
        else:
            mode, source = FALLBACK, "fallback"
        floor = bars.get(key)
        # `on` with no floor has no meaning, so it reads `shadow` and says why.
        held = mode == "on" and floor is None
        out[key] = {"mode": "shadow" if held else mode, "from": source,
                    "floor": floor, "held": held, "asked": mode}
    return out


def line(key: str, entry: dict) -> str:
    """One line of the effective table, for a verb or a report."""
    said = f"{key:<19} {entry['mode']:<7} ({entry['from']}"
    said += f", floor {entry['floor']:g})" if entry["floor"] is not None else ")"
    if entry["held"]:
        said += "  [asked for on, held at shadow: no floor is set]"
    return said


# ----- writing the override -----

def write_override(state_dir: Path, key: str, mode: str | None) -> None:
    """Set or clear one key, by a temp file and a rename, so a reader never sees a
    half-written switch. `mode=None` removes the override and hands the key back to the
    default."""
    if key not in KEYS:
        raise SwitchError(f"{key!r} is not a judge key: {', '.join(KEYS)}")
    if mode is not None and mode not in MODES:
        raise SwitchError(f"{mode!r} is not a mode: {', '.join(MODES)}, or default to clear")
    directory = state_dir / "voice"
    directory.mkdir(parents=True, exist_ok=True)
    current = overrides(state_dir)
    if mode is None:
        current.pop(key, None)
    else:
        current[key] = mode
    target = directory / SWITCH_FILE
    tmp = target.with_name(target.name + ".new")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, target)


def log_flip(state_dir: Path, key: str, before: dict, after: dict) -> None:
    """Append the flip to the shadow log, because "he read the report and said so" was a
    commit until today and now needs a record of its own."""
    directory = state_dir / "voice"
    directory.mkdir(parents=True, exist_ok=True)
    row = {"at": _now(), "kind": "flip", "key": key,
           "from": before["mode"], "from_source": before["from"],
           "to": after["mode"], "to_source": after["from"],
           "by": f"{os.environ.get('USER') or 'unknown'}@{socket.gethostname()}"}
    with (directory / LOG_FILE).open("a") as out:
        out.write(json.dumps(row) + "\n")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


# ----- the report -----

def rows(path: Path) -> list[dict]:
    """Every JSON object line of a jsonl file, skipping what does not parse; empty when the
    file cannot be read. The log and the transcript are both append-only and read whole."""
    try:
        text = path.read_text()
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def transcript_turns(state_dir: Path) -> set[str]:
    """The turn ids the gateway's transcript names: a turn that really happened."""
    return {str(row["turn"]) for row in rows(state_dir / "voice" / TRANSCRIPT_FILE)
            if row.get("turn")}


def on_transcript(calls: list[dict], turns: set[str]) -> tuple[list[dict], int]:
    """(the calls about a real turn, how many were not).

    A CALL WITH NO TRANSCRIPT TURN IS NOT EVIDENCE (c-542, c-552). On the live log on
    2026-09-27, 16 judge rows had none: a selftest writing narrate rows into the live log in
    bursts, four with a canned 0.05 s latency. Counting them made `narrate` look asked about
    turns that never happened, so they are dropped here and counted, never tallied."""
    kept = [row for row in calls if str(row.get("turn") or "") in turns]
    return kept, len(calls) - len(kept)


def read_log(state_dir: Path) -> tuple[list[dict], dict[str, str], list[dict]]:
    """The log split into what each kind of line is for: the calls, the outcome per turn,
    and the flips. One pass, because the file is append-only and read whole."""
    calls, outcomes, flips = [], {}, []
    for row in rows(state_dir / "voice" / LOG_FILE):
        kind = row.get("kind") or "call"
        if kind == "outcome":
            outcomes.setdefault(str(row.get("turn") or ""), str(row.get("outcome") or ""))
        elif kind == "flip":
            flips.append(row)
        else:
            calls.append(row)
    return calls, outcomes, flips


def per_key(calls: list[dict]) -> dict[str, dict]:
    """One tally per switch key: calls, agreement with the rule, misses, latencies.

    A call line carries every answer the judge was asked, so one call feeds several keys.
    Agreement is counted only where Jev actually answered: a miss is not a disagreement,
    it is an absence, and counting it as either would flatter or damn the model wrongly."""
    tally = {key: {"calls": 0, "answered": 0, "agreed": 0, "misses": {}, "seconds": []}
             for key in KEYS}
    for row in calls:
        judge = str(row.get("judge") or "")
        jev = row.get("jev") or {}
        rule = row.get("rule") or {}
        miss = str(row.get("miss") or "")
        for answer in (row.get("modes") or {}):
            key = answer if judge == answer else f"{judge}.{answer}"
            if key not in tally:
                continue
            entry = tally[key]
            entry["calls"] += 1
            if miss:
                entry["misses"][miss] = entry["misses"].get(miss, 0) + 1
                continue
            said = (jev.get(answer) or {})
            if "value" not in said:
                entry["misses"]["no-answer"] = entry["misses"].get("no-answer", 0) + 1
                continue
            entry["answered"] += 1
            if said.get("value") == rule.get(answer):
                entry["agreed"] += 1
            if isinstance(row.get("latency"), (int, float)):
                entry["seconds"].append(float(row["latency"]))
    return tally


def disagreements(calls: list[dict], outcomes: dict[str, str], limit: int = 10) -> list[dict]:
    """The lines worth reading: Jev disagreed with the rule AND was confident about it.

    Newest first and capped, because a report nobody finishes is a report nobody reads.
    The outcome is joined in, since it is the thing that says who was right."""
    found = []
    for row in reversed(calls):
        if row.get("miss"):
            continue
        rule, jev = row.get("rule") or {}, row.get("jev") or {}
        for answer, said in jev.items():
            if not isinstance(said, dict) or "value" not in said:
                continue
            if said["value"] == rule.get(answer):
                continue
            found.append({"at": row.get("at"), "turn": row.get("turn"),
                          "judge": row.get("judge"), "answer": answer,
                          "text": (row.get("text") or "") if shown_personal(row) else "",
                          "rule": rule.get(answer),
                          "jev": said["value"], "confidence": said.get("confidence"),
                          "outcome": outcomes.get(str(row.get("turn") or "")) or "unknown"})
            if len(found) >= limit:
                return found
    return found


def shown_personal(row: dict) -> bool:
    """May this call line's words be printed (c-552)? Only when its own facts show a
    personal turn: the page not in the work space and no card pinned, whose space this
    module cannot see. A line from before c-552 carries no facts and is never shown.

    "No work turn's words in any output" is his rule for the judges' reports, and this
    report has no board to ask. Withholding a personal line's words costs a reading;
    printing a work line's would be the leak the rule exists to prevent."""
    facts = row.get("facts")
    return (isinstance(facts, dict) and facts.get("space") != "work"
            and not facts.get("card"))


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(share * len(ordered) + 0.5))))
    return ordered[rank - 1]


def report(toml_path: Path, state_dir: Path, limit: int = 10) -> list[str]:
    """`keel voice judges`: what the shadow log says, per key, in one screen."""
    modes = effective(toml_path, state_dir)
    calls, outcomes, flips = read_log(state_dir)
    calls, skipped = on_transcript(calls, transcript_turns(state_dir))
    tally = per_key(calls)
    lines = ["the switch"]
    lines += ["  " + line(key, modes[key]) for key in KEYS]
    lines.append("")
    lines.append(f"{'key':<19} {'calls':>6} {'agreed':>7} {'p50':>7} {'p95':>7}   misses")
    for key in KEYS:
        entry = tally[key]
        agreed = (f"{100 * entry['agreed'] / entry['answered']:.0f}%"
                  if entry["answered"] else "-")
        misses = ", ".join(f"{name} {count}" for name, count
                           in sorted(entry["misses"].items())) or "none"
        lines.append(f"{key:<19} {entry['calls']:>6} {agreed:>7} "
                     f"{_ms(percentile(entry['seconds'], 0.50)):>7} "
                     f"{_ms(percentile(entry['seconds'], 0.95)):>7}   {misses}")
    if skipped:
        lines.append(f"skipped {skipped} call rows with no transcript turn (not real turns)")
    worth = disagreements(calls, outcomes, limit)
    lines.append("")
    if not worth:
        lines.append("no disagreements yet" if calls else
                     "nothing logged yet: no judge has been asked on this machine")
    else:
        lines.append(f"disagreements worth reading ({len(worth)}, newest first)")
        for item in worth:
            lines.append(f"  {item['judge']}.{item['answer']}  rule {item['rule']!r} "
                         f"vs jev {item['jev']!r} at {item['confidence']}  "
                         f"then: {item['outcome']}")
            lines.append(f"    {_clip(item['text'])}" if item["text"] else
                         f"    turn {item['turn']} (words withheld: not shown to be "
                         f"a personal turn)")
    if flips:
        lines.append("")
        lines.append("flips")
        for row in flips[-5:]:
            lines.append(f"  {row.get('at')}  {row.get('key')}  "
                         f"{row.get('from')} -> {row.get('to')}  by {row.get('by')}")
    return lines


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms" if seconds else "-"


def _clip(text: str, width: int = 90) -> str:
    said = " ".join(str(text).split())
    return said if len(said) <= width else said[: width - 1] + "…"
