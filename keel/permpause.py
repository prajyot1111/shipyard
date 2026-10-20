"""A house auto mode paused on a permission prompt nobody can answer (c-528).

The box, 2026-09-25: c-521's house had three commands denied by auto mode's classifier
(`git reset --hard`, then two read-only `git show | grep`). Past its denial limit auto mode
stops deciding and opens a permission prompt for a human, and a background session has
nobody in front of it. The house cannot tell it is stuck; the card sat at `planning` with
no block and the drain counted it as a live house for over 30 minutes.

The harness says so in two places, and this module reads only those, never a timer:

- `claude agents --json` lists the session `status: "waiting"` with `waitingFor` (a
  permission dialog is `"permission prompt"`), read from the 2.1.283 binary on 2026-09-26;
- the Notification hook fires with `notification_type: permission_prompt`, which the house's
  settings record on the card (`house.NOTIFICATION_MATCHER`).

The drain (`drain.permission_upkeep`) blocks such a card with the commands denied in the
current turn, read from the transcript, and clears its OWN block when the harness later
shows that same session busy again: the prompt can deny by itself after a while, and a
house that carried on must not sit in his needs-you.

No Keel imports beyond the harness: the drain owns which cards are looked at.
"""

import json
import re
from pathlib import Path

from keel import harness

PERMISSION_PROMPT = "permission_prompt"
WAITING = "waiting"
# The listing's `waitingFor` for a permission dialog (2.1.283: any dialog without its own
# word). Another dialog (an MCP input, a billing notice) is not this card's pause.
PERMISSION_WAIT = "permission prompt"
TURN_END_HOOKS = ("Stop", "SessionEnd")
# What ends the stretch of events signal B reads: a new turn, or a block answered since.
TURN_STARTS = ("resume", "session", "unblock")
# The data on the drain's block, which is what `drive.state_of` wakes Bosun with and what a
# later pass recognises as its own block to clear.
MARK = "permission-pause"
# The harness's own words for a denied call: auto mode's classifier, and a permission rule.
# Never a bare "Permission denied", which is the filesystem's.
DENIED = re.compile(r"^Permission (for this action was|to use \S+ (has been|was)) denied")
# What the drain's reason says happened, which is how `holds_slot` knows the block without an
# event; it follows `ACTION`, since a reason opens with what can be done (c-584). A block
# written before that opened with this, and still reads as one.
HEAD = "auto mode paused this house on a permission prompt nobody can answer"
ACTION = "Resume it with a way round that does not need the denied command."
REASON = re.compile(r"Reason: \[([^\]]+)\]")
MAX_DENIALS = 5
CLIP = 300
INPUT_KEYS = ("command", "file_path", "url", "pattern", "path", "prompt")


# ----- the signal -----

def own_row(card: dict, rows: list[dict]) -> dict | None:
    return harness.find(card.get("session_id") or "", rows)


def prompted(board, card: dict) -> bool:
    """Signal B: the newest Notification from the card's own session in this turn is a
    permission prompt, with no Stop or SessionEnd after it and no block answered since."""
    for event in reversed(board.events(card["id"])):
        if event["kind"] in TURN_STARTS:
            return False
        data = event["data"] or {}
        if event["kind"] != "hook" or data.get("session_id") not in (None, card.get("session_id")):
            continue
        if data.get("hook") in TURN_END_HOOKS:
            return False
        if data.get("hook") == "Notification":
            return (data.get("payload") or {}).get("notification_type") == PERMISSION_PROMPT
    return False


def waiting_for(board, card: dict, rows: list[dict]) -> str | None:
    """What the house's permission pause is waiting for, or None when it is not paused.

    Signal A, the listing's `waiting` status with `waitingFor` a permission prompt; signal
    B, the hook, covers a listing that says `idle` instead. Busy, gone from the listing, or
    waiting on some other dialog is never it."""
    row = own_row(card, rows)
    if row is None or row.get("status") == "busy":
        return None
    if row.get("status") == WAITING:
        return PERMISSION_WAIT if row.get("waitingFor") == PERMISSION_WAIT else None
    return PERMISSION_WAIT if prompted(board, card) else None


# ----- what was denied -----

def records(path: str | Path) -> list[dict]:
    try:
        lines = Path(path).expanduser().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for raw in lines:
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict) and not record.get("isSidechain"):
            out.append(record)
    return out


def blocks(record: dict) -> list:
    content = (record.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


# User records the harness writes inside a turn rather than at its start.
NOT_A_PROMPT = ("isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")


def is_prompt(record: dict) -> bool:
    """A user record that starts a turn: text from him or Keel, not a tool's result, and
    not one the harness injects mid-turn (a compaction summary, a meta reminder)."""
    if record.get("type") != "user" or any(record.get(flag) for flag in NOT_A_PROMPT):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return any(isinstance(b, dict) and b.get("type") == "text" for b in blocks(record)) and \
        not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks(record))


def this_turn(rows: list[dict]) -> list[dict]:
    for index in range(len(rows) - 1, -1, -1):
        if is_prompt(rows[index]):
            return rows[index + 1:]
    return rows


def result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content or "")


def one_line(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= CLIP else text[:CLIP - 1] + "…"


# What a denied command may carry that must never reach the board, the deck or Bosun's
# prompt: a header's value, a bearer token, and a `key=value` or a `--flag value` whose
# name says it is a secret.
SECRETS = (
    re.compile(r"(?i)((?:-H|--header)\s+['\"]?[\w-]+:\s*)[^'\"]+"),
    re.compile(r"(?i)\b(bearer|basic)\s+[\w.+/=-]+"),
    re.compile(r"(?i)([\w-]*(?:token|secret|password|passwd|key|cookie|auth)[\w-]*\s*[=:]\s*)"
               r"(['\"]?)[^\s'\"&;]+"),
    re.compile(r"(?i)(--?[\w-]*(?:token|secret|password|passwd|key|cookie|auth)[\w-]*\s+)"
               r"(['\"]?)[^\s'\"&;]+"),
)


def redact(text: str) -> str:
    text = SECRETS[0].sub(r"\1[redacted]", text)
    text = SECRETS[1].sub(r"\1 [redacted]", text)
    text = SECRETS[2].sub(r"\1\2[redacted]", text)
    return SECRETS[3].sub(r"\1\2[redacted]", text)


def render_call(name: str, given: dict) -> str:
    for key in INPUT_KEYS:
        if isinstance(given, dict) and given.get(key):
            return f"{name}: {one_line(redact(str(given[key])))}"
    return f"{name}: {one_line(redact(json.dumps(given, ensure_ascii=False)))}"


def denials(path: str | Path) -> dict:
    """The current turn's denied tool calls, oldest first (at most the newest five), each
    with the classifier's reason, and the call still waiting on an answer, if any."""
    calls: dict[str, str] = {}
    denied: list[str] = []
    answered: set[str] = set()
    for record in this_turn(records(path)):
        for block in blocks(record):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block.get("id")] = render_call(block.get("name") or "tool", block.get("input") or {})
            elif block.get("type") == "tool_result":
                answered.add(block.get("tool_use_id"))
                text = result_text(block)
                if DENIED.match(text.lstrip()):
                    reason = REASON.search(text)
                    call = calls.get(block.get("tool_use_id"), "a tool call")
                    denied.append(call + (f" [{reason.group(1)}]" if reason else ""))
    pending = [call for key, call in calls.items() if key not in answered]
    return {"denied": denied[-MAX_DENIALS:], "pending": pending[-1] if pending else None}


# ----- the block -----

def transcript(board, card: dict) -> str | None:
    """The transcript of the card's CURRENT session, from its hooks; an older session's
    would name another turn's commands."""
    for event in reversed(board.events(card["id"])):
        data = event["data"] or {}
        path = data.get("transcript_path") or (data.get("payload") or {}).get("transcript_path")
        session = data.get("session_id") or (data.get("payload") or {}).get("session_id")
        if path and session == card.get("session_id"):
            return path
    return None


def reason(what: str, found: dict) -> str:
    lines = [ACTION, f"{HEAD[0].upper()}{HEAD[1:]} (the harness says it is waiting for: {what})."]
    if found["denied"]:
        lines.append("Denied in this turn:")
        lines += [f"- {call}" for call in found["denied"]]
    if found["pending"]:
        lines.append(f"Waiting on: {found['pending']}")
    if not found["denied"] and not found["pending"]:
        lines.append("The transcript did not say which commands were denied.")
    return "\n".join(lines)


def block(board, card: dict, what: str) -> str:
    path = transcript(board, card)
    found = denials(path) if path else {"denied": [], "pending": None}
    text = reason(what, found)
    board.block(card["id"], text, "drain", mark=MARK)
    return text


def paused_block(card: dict) -> bool:
    """The card's block is the drain's permission pause, read from its text alone: its
    second line since c-584, its first before."""
    return HEAD in str(card.get("blocked_reason") or "").lower()


def own_block(board, card: dict) -> dict | None:
    """The drain's permission block still standing on this card for its CURRENT session, as
    its event; None once a newer session was recorded (a resume), or for any other block.
    Board facts only, so a remote board (the Mac's) answers the same."""
    if not paused_block(card):
        return None
    for event in reversed(board.events(card["id"])):
        if event["kind"] == "session":
            return None
        if event["kind"] == "block":
            ours = event["actor"] == "drain" and (event["data"] or {}).get("paused") == "permission"
            return event if ours and event["text"] == card["blocked_reason"] else None
    return None


def stopped_since(board, card: dict) -> bool:
    """A Stop from the card's own session after the drain's block: its turn went on past
    the prompt and ended, which a pass that never saw it busy would otherwise miss."""
    for event in reversed(board.events(card["id"])):
        if event["kind"] == "block":
            return False
        data = event["data"] or {}
        if event["kind"] == "hook" and data.get("hook") == "Stop" and \
                data.get("session_id") in (None, card.get("session_id")):
            return True
    return False


def recovered(board, card: dict, rows: list[dict]) -> bool:
    """D1: the drain's own block stands and the same session carried on past the prompt,
    which is the prompt denying by itself: seen busy again, or a Stop since the block."""
    if own_block(board, card) is None:
        return False
    row = own_row(card, rows)
    return (row is not None and row.get("status") == "busy") or stopped_since(board, card)


def clear(board, card: dict) -> bool:
    """Take the drain's block off, only while it is still that exact block; True when it
    did, so nothing is noted or counted for a block he replaced in between."""
    after = board.unblock(card["id"], "drain", expect=card["blocked_reason"])
    if after.get("blocked_reason"):
        return False
    board.note(card["id"], "the permission prompt closed and the house is working again; "
                           "the drain's block is cleared", "drain")
    return True
