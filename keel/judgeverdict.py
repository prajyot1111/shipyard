"""The verdict per judge key: flip on, drop, or needs more data (c-552).

`keel voice judges` says what the shadow log holds. This says what it EARNS, by the bar he
approved on c-542: a key flips on only with at least 30 personal turns whose truth is known,
and the 95% Wilson lower bound of Jev on its confident calls (0.9 or more) above the rule's
own rate on the same turns. It is c-542's hand method (`state/cards/c-542/shadow_stats.py`)
made a command, so the week's run is one line rather than a research card.

AGREEMENT IS NOT ACCURACY. The rule is what decided, so "Jev agreed with the rule" says
nothing about who was right. Truth comes from two places, his call at c-552's plan gate:

- OUTCOME ROWS, where the log itself says what happened: the card the talker connected to
  (`card`), the first deck read the talker made (`prefetch`), a held half sentence that got
  the rest of itself (`complete`), and a push-to-talk listen, which is addressed by
  definition (`addressed`).
- A LABELS FILE for the rest, `state/voice/judge-labels.json`, keyed by turn id: a person's
  reading of each turn, `null` where it cannot be read. A label beats an outcome. The
  command lists the turn ids still worth labelling, ids only.

PERSONAL ROWS ONLY, c-542's exclude rule made mechanical. A row counts when a label says its
space is personal, or when the card it touches is personal on the board, or, with no card,
when its page was not in the work space and its session (turns under 15 minutes apart)
touched no work card and matched no adapter's vocabulary. A row with none of those facts
(anything logged before c-552) counts only by a label. Everything else is excluded and only
counted.

NO WORDS, EVER. Nothing here prints what was said, in either space: turn ids, keys, counts
and verdicts. The text is read only to match an adapter's vocabulary against it.
"""

import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from keel import judges

FLOOR = 0.9                 # a confident call, for the Wilson bar he approved (c-542)
MIN_TURNS = 30              # personal turns with a known truth before any verdict but "more"
Z = 1.96                    # 95%
SESSION_GAP = 15 * 60       # seconds between turns that still make one session (c-542)
LABELS_FILE = "judge-labels.json"
TODO_CAP = 10               # turn ids listed per key to label


# ----- the numbers -----

def wilson(right: int, n: int, z: float = Z) -> tuple[float, float]:
    """The Wilson score interval for `right` of `n`: (lower, upper). (0, 1) with no calls."""
    if n <= 0:
        return 0.0, 1.0
    p = right / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - spread) / d), min(1.0, (centre + spread) / d)


def decide(truthed: int, confident: int, lower: float, upper: float,
           rule_rate: float) -> str:
    """The bar, and nothing else. `flip on` needs the turns and the bound above the rule;
    `drop` needs the turns and a log that rules against Jev: never confident at all, or
    confidently worse than the rule even at the top of its interval."""
    if truthed >= MIN_TURNS and confident and lower > rule_rate:
        return "flip on"
    if truthed >= MIN_TURNS and (not confident or upper < rule_rate):
        return "drop"
    return "needs more data"


# ----- reading -----

def _stamp(at: str) -> float | None:
    try:
        return datetime.strptime(str(at), "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return None


def labels(paths: list[Path]) -> dict[str, dict]:
    """Every labels file given, merged in order (a later file wins a turn's answer)."""
    out: dict[str, dict] = {}
    for path in paths:
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        for turn, entry in doc.items():
            if turn.startswith("_") or not isinstance(entry, dict):
                continue
            out.setdefault(str(turn), {}).update(entry)
    return out


def vocabulary(*roots: Path) -> list[re.Pattern]:
    """Each adapter's and pack's `hearing.json` words and what they stand for, as word
    patterns: the names a work remark would carry. Read generically, so nothing here names
    one. `roots` are the adapters dir and every pack root (an install's own pack is not in
    the code, c-722)."""
    words: set[str] = set()
    for path in sorted(path for root in roots for path in Path(root).glob("*/hearing.json")):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for table in ("words", "phrases"):
            for heard, entry in (doc.get(table) or {}).items():
                words.add(str(heard))
                if isinstance(entry, dict) and entry.get("said"):
                    words.add(str(entry["said"]))
    return [re.compile(r"\b" + re.escape(word) + r"\b", re.I)
            for word in sorted(words) if len(word) > 2]


# ----- which rows count -----

def _outcomes(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("kind") == "outcome":
            out.setdefault(str(row.get("turn") or ""), []).append(row)
    return out


def _connected(outcomes: list[dict]) -> str:
    for row in outcomes:
        if row.get("outcome") == "connected" and row.get("card"):
            return str(row["card"])
    return ""


def spaces(calls: list[dict], outcomes: dict, marks: dict, space_of,
           words: list[re.Pattern]) -> dict[int, str]:
    """`{index into calls: "personal" | "work" | "unknown"}`, by the rule in the docstring.

    Sessions are cut on the calls' own clock, in log order, because the log is written in
    the order the turns happened."""
    own: dict[int, str] = {}
    session_of: dict[int, int] = {}
    tainted: set[int] = set()
    session, last = 0, None
    for index, row in enumerate(calls):
        at = _stamp(row.get("at"))
        if last is None or at is None or at - last >= SESSION_GAP:
            session += 1
        last = at if at is not None else last
        session_of[index] = session
        facts = row.get("facts") if isinstance(row.get("facts"), dict) else None
        turn = str(row.get("turn") or "")
        card = (facts or {}).get("card") or _connected(outcomes.get(turn, []))
        card_space = space_of(card) if card else ""
        text = str(row.get("text") or "")
        work = (card_space and card_space != "personal") or \
            (facts or {}).get("space") == "work" or any(p.search(text) for p in words)
        if work:
            tainted.add(session)
        if card_space:
            own[index] = "personal" if card_space == "personal" else "work"
        elif facts is None:
            own[index] = "unknown"
        else:
            own[index] = ""                 # decided by its session, below
    out = {}
    for index, row in enumerate(calls):
        said = (marks.get(str(row.get("turn") or "")) or {}).get("space")
        if said:
            out[index] = "personal" if said == "personal" else "work"
        elif own[index]:
            out[index] = own[index]
        else:
            out[index] = "work" if session_of[index] in tainted else "personal"
    return out


# ----- truth -----

_MISSING = object()


def truth(answer: str, row: dict, outcomes: list[dict], mark: dict):
    """What was right for one answer on one call: a value, None (unclear), or `_MISSING`."""
    if answer in mark:
        return mark[answer]
    facts = row.get("facts") if isinstance(row.get("facts"), dict) else None
    said = {o.get("outcome") for o in outcomes}
    if answer == "addressed" and facts is not None and facts.get("hands_free") is False:
        return True
    if answer == "complete":
        if "carried-on" in said:
            return False
        if "abandoned" in said:
            return True
    if answer == "card":
        card = _connected(outcomes)
        if card:
            return card
        if said:
            return "none"
    if answer == "prefetch":
        for o in outcomes:
            if o.get("outcome") == "reads":
                sections = [str(s) for s in (o.get("sections") or []) if s]
                return sections[0] if sections else "none"
    return _MISSING


# ----- the verdict -----

def _key_of(judge: str, answer: str) -> str:
    return answer if judge == answer else f"{judge}.{answer}"


def _in_window(row: dict, since: date, days: int) -> bool:
    day = str(row.get("at") or "")[:10]
    return since.isoformat() <= day < (since + timedelta(days=days)).isoformat()


def verdict(state_dir: Path, since: date, days: int = 7, label_paths=(),
            space_of=lambda card: "", words=()) -> dict:
    """Everything the command prints, as data: the window, the rows, and one entry per key."""
    everything = judges.rows(state_dir / "voice" / judges.LOG_FILE)
    calls = [row for row in everything if (row.get("kind") or "call") == "call"]
    kept, skipped = judges.on_transcript(calls, judges.transcript_turns(state_dir))
    window = [row for row in kept if _in_window(row, since, days)]
    outcomes = _outcomes(everything)
    marks = labels(list(label_paths))
    where = spaces(window, outcomes, marks, space_of, list(words))
    keys = {key: _empty() for key in judges.KEYS}
    for index, row in enumerate(window):
        judge = str(row.get("judge") or "")
        turn = str(row.get("turn") or "")
        for answer in (row.get("modes") or {}):
            key = _key_of(judge, answer)
            if key in keys:
                _count(keys[key], answer, row, where[index], outcomes.get(turn, []),
                       marks.get(turn, {}))
    for entry in keys.values():
        _finish(entry)
    return {"since": since.isoformat(), "days": days,
            "until": (since + timedelta(days=days - 1)).isoformat(),
            "rows": len(window), "skipped": skipped, "keys": keys}


def _empty() -> dict:
    return {"turns": 0, "personal": 0, "answered": 0, "truthed": 0, "rule_right": 0,
            "confident": 0, "confident_right": 0, "seconds": [], "questions": [],
            "todo": []}


def _count(entry: dict, answer: str, row: dict, space: str, outcomes: list, mark: dict):
    entry["turns"] += 1
    said = (row.get("jev") or {}).get(answer)
    answered = not row.get("miss") and isinstance(said, dict) and "value" in said
    if answered and isinstance(row.get("latency"), (int, float)):
        entry["seconds"].append(float(row["latency"]))
        if isinstance(row.get("questions"), int):
            entry["questions"].append(row["questions"])
    if space != "personal":
        return
    entry["personal"] += 1
    if not answered:
        return
    entry["answered"] += 1
    right = truth(answer, row, outcomes, mark)
    if right is _MISSING:
        if len(entry["todo"]) < TODO_CAP:
            entry["todo"].append(str(row.get("turn") or ""))
        return
    if right is None:
        return                              # unclear: out of both rates, as c-542 did
    entry["truthed"] += 1
    if (row.get("rule") or {}).get(answer) == right:
        entry["rule_right"] += 1
    if float(said.get("confidence") or 0) >= FLOOR:
        entry["confident"] += 1
        if said.get("value") == right:
            entry["confident_right"] += 1


def _finish(entry: dict) -> None:
    rate = entry["rule_right"] / entry["truthed"] if entry["truthed"] else 0.0
    lower, upper = wilson(entry["confident_right"], entry["confident"])
    entry["rule_rate"] = rate
    entry["lower"], entry["upper"] = lower, upper
    entry["p50"] = judges.percentile(entry["seconds"], 0.50)
    entry["p95"] = judges.percentile(entry["seconds"], 0.95)
    entry["over"] = sum(1 for s in entry["seconds"] if s > 0.6)
    entry["verdict"] = decide(entry["truthed"], entry["confident"], lower, upper, rate)


# ----- printing -----

def lines(doc: dict) -> list[str]:
    """The report, one block per key, narrow enough for a phone. Never a word he said."""
    out = [f"window {doc['since']} to {doc['until']} ({doc['days']} days): "
           f"{doc['rows']} call rows on a transcript turn"]
    if doc["skipped"]:
        out.append(f"skipped {doc['skipped']} call rows with no transcript turn (all time)")
    out.append(f"bar: {MIN_TURNS}+ personal turns with a known truth, and the Wilson lower "
               f"bound of Jev at {FLOOR:g}+ above the rule's rate")
    todo = []
    for key in judges.KEYS:
        e = doc["keys"][key]
        out.append("")
        out.append(f"{key:<19} {e['verdict'].upper()}")
        out.append(f"  turns {e['turns']}, personal {e['personal']} "
                   f"({e['turns'] - e['personal']} excluded), Jev answered {e['answered']}, "
                   f"truth known {e['truthed']}")
        if e["truthed"]:
            out.append(f"  rule right {e['rule_right']}/{e['truthed']} "
                       f"({100 * e['rule_rate']:.0f}%), Jev confident {e['confident']}, "
                       f"right {e['confident_right']}, Wilson "
                       f"{e['lower']:.2f} to {e['upper']:.2f}")
        if e["seconds"]:
            asked = (f", {sum(e['questions']) / len(e['questions']):.1f} questions a call"
                     if e["questions"] else "")
            out.append(f"  latency p50 {_ms(e['p50'])}, p95 {_ms(e['p95'])}, "
                       f"{e['over']} of {len(e['seconds'])} over 600ms{asked}")
        if e["todo"]:
            todo.append(f"  {key}: {', '.join(e['todo'])}")
    if todo:
        out.append("")
        out.append(f"to label (turn ids only, up to {TODO_CAP} a key), in "
                   f"state/voice/{LABELS_FILE}")
        out += todo
    return out


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms" if seconds else "-"
