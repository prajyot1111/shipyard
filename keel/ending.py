"""The other half of the Stop hook: what Keel checks when a house ends a turn.

`kb stop-check` (in `board`) owns one rule, the nudge at `building`. This module owns the
two that belong to the gates, and the card's news, and runs beside it, as the second
command of the same Stop hook group:

- **The record at the outcome gate.** Harbor's c-255 found that nobody ever asked a house
  for evidence, so cards arrived at review with a template `context.md` and no screenshot.
  A Stop for a card at `review` reads the record and, if a section is missing, empty, or
  Evidence names no artifact, sends the house back ONCE with the sections named. The nudge
  is marked `options.record_nudged` so it can never fire twice for a card: a house that has
  answered, or has said why there is nothing to show, is not asked again. An ask card
  (`options.drop`) is exempt: its record is the drop, which is why the card is at review
  at all. So is a review card (lane RC): its record is the review kind, which the lint at
  `kb stage review` holds (C28 to C31).
- **The discussion flag.** `options.discussion` is set when a house is resumed into a plan
  discussion and cleared here, because the Stop for that card is exactly the moment its
  loop ended. The deck reads `options.discussion` to show a card as talking.
- **The card's news** (c-533, `with_news`). A briefed field changed since the house
  started (`keel/briefnews.py`) is told at a Stop at planning or building, once.

And when the turn does end (no rule above sent it back), a card with a relay pending for
this machine kicks this machine's drain (`kick.after_stop`, c-598): a tap held while the
house worked is told to it now.

A Stop whose payload still carries running background tasks is a wait, not a stop (the
harness re-invokes the session when that work hands back), so none of them fires on it.
Neither fires on a card voice is holding either (`options.voice_hold`, guard 3 of V4): a
connected turn ends with a Stop like any other turn, and neither the record nudge nor the
discussion flag is about a sentence he is waiting to hear back.
Nothing here ever ends a session, and an exception never leaves `main`: a hook that fails
must not keep a house from stopping.
"""

import json
import re
import sys
from pathlib import Path

from keel import briefnews, config as config_module, kick, views
from keel.board import DROP_OPTION, Board, open_board, running_background_tasks
from keel.review import gate as review_gate

RECORD_SECTIONS = ("Where it stands", "What is next", "Why this shape", "Open questions", "Evidence")
EVIDENCE = "Evidence"
NUDGE_OPTION = "record_nudged"
DISCUSSION_OPTION = "discussion"
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")
# Only the stand-ins that say nothing. "None" and "n/a" are left out on purpose: they are a
# real answer to Open questions, and Evidence is judged on whether it names something instead.
PLACEHOLDERS = {"", "tbd", "to be decided", "todo", "to do", "tk", "xxx", "-", "--", "...",
                "(fill in)", "fill in"}
ARTIFACT = re.compile(
    r"assets/\S+"                                   # the card's own assets directory
    r"|!?\[[^\]]*\]\([^)]+\)"                       # a markdown image or link
    r"|https?://\S+"                                # a pull request, a story, a page
    r"|`[^`]*[./][^`]*`"                            # a backticked path or command output
    r"|\b[\w./-]+\.(?:png|jpg|jpeg|gif|svg|pdf|html|md|json|txt|log|csv|diff|patch)\b",
    re.IGNORECASE)
EVIDENCE_GAP = ("Evidence has no screenshot or artifact; embed it as "
                "![what it shows](assets/<file>) or say why there is none")


# ----- reading the record -----

def sections(text: str) -> dict[str, str]:
    """Heading -> body, for the headings of a `context.md`."""
    found: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            current = match.group(1).strip()
            found.setdefault(current, "")
        elif current is not None:
            found[current] += line + "\n"
    return found


def is_placeholder(body: str) -> bool:
    """An empty section, or one still carrying the template's stand-in for real words."""
    stripped = body.strip().strip("*_`> ").strip().lower()
    return stripped in PLACEHOLDERS


def names_an_artifact(body: str) -> bool:
    return bool(ARTIFACT.search(body))


def record_gaps(text: str) -> list[str]:
    """The sections that would make a reader none the wiser, in the record's own order."""
    found = sections(text)
    gaps = []
    for heading in RECORD_SECTIONS:
        body = found.get(heading)
        if body is None:
            gaps.append(f"{heading} is missing")
        elif heading == EVIDENCE:
            # Evidence is the section c-255 found empty every time, so it gets the same
            # answer whether it is blank or is prose that names nothing to look at.
            if is_placeholder(body) or not names_an_artifact(body):
                gaps.append(EVIDENCE_GAP)
        elif is_placeholder(body):
            gaps.append(f"{heading} is empty")
    return gaps


def gap_reason(card_id: str, path: Path, gaps: list[str]) -> str:
    return (f"Card {card_id} is at the outcome gate, but its record is not finished: "
            + "; ".join(gaps) + f". Fill that in {path}, then end your turn.")


def context_text(cfg, card_id: str) -> tuple[Path, str]:
    path = cfg.cards_dir / card_id / "context.md"
    try:
        return path, path.read_text()
    except OSError:
        return path, ""


# ----- the two rules -----

def clear_discussion(board: Board, card: dict) -> bool:
    """A discussion ends when the turn it runs in ends; the flag goes with it."""
    if not card["options"].get(DISCUSSION_OPTION):
        return False
    board.set_fields(card["id"], {"options": {DISCUSSION_OPTION: False}}, "hook")
    return True


MERGING_OPTION = "merging"


def clear_merging(board: Board, card: dict) -> bool:
    """`options.merging` is set when an approved outcome could not be merged because the
    target moved, and the house was sent to merge it; it is done when the house is back at
    review, which is the turn end this hook sees. At building (a nudge) it stays."""
    if not card["options"].get(MERGING_OPTION) or card["stage"] != "review":
        return False
    board.set_fields(card["id"], {"options": {MERGING_OPTION: False}}, "hook")
    return True


def record_check(board: Board, cfg, card: dict) -> dict | None:
    """Send the house back once when the record at the outcome gate is thin."""
    if card["stage"] != "review" or card["options"].get(NUDGE_OPTION):
        return None
    if card["options"].get(DROP_OPTION):
        # An ask card's record IS its drop, and `kb stop-check` filed the card the moment
        # that file appeared. Asking its house for a six-heading context.md would ask a
        # session with no shell, and usually nothing left to say, for a second record.
        return None
    if review_gate.is_review_card(card):
        # A review card's record is the review kind (lane RC), held to ITS shape by the
        # lint at `kb stage review` (C28 to C31); the five build sections are not its own.
        return None
    path, text = context_text(cfg, card["id"])
    gaps = record_gaps(text)
    if not gaps:
        return None
    reason = gap_reason(card["id"], path, gaps)
    board.set_fields(card["id"], {"options": {NUDGE_OPTION: True}}, "hook")
    board.note(card["id"], reason, "hook")
    return {"decision": "block", "reason": reason}


def check(cfg, board: Board, card_id: str, payload: dict | None) -> dict | None:
    """The hook's answer: `{"decision": "block"}` at most once per card, else nothing."""
    card = board.get(card_id)
    if running_background_tasks(payload):
        return None
    if views.voice_hold(card.get("options")):
        return None
    clear_discussion(board, card)
    clear_merging(board, card)
    refused = review_gate.check(cfg, board, card, payload)
    if refused:
        return refused
    after = board.get(card_id)
    if after.get("blocked_reason") and not card.get("blocked_reason"):
        return None                 # the review gate handed it to him this Stop
    return with_news(board, cfg, after, record_check(board, cfg, after))


def tap_waiting(cfg, card: dict) -> bool:
    """His tap for this house waits for its turn to end (`views.held_tap`, c-604)."""
    relays = (card.get("derived") or {}).get("relays")
    return views.held_tap(relays, card.get("session_id"), getattr(cfg, "host", None)) is not None


# ----- the card's news (c-533) -----

NEWS_STAGES = ("planning", "building")


def with_news(board: Board, cfg, card: dict, decision: dict | None) -> dict | None:
    """Tell the house a briefed field changed since it started, when no other rule blocked.

    Only at planning or building on an unblocked card that is not rotating: those are the
    turns the change alters, and no rule here blocks at either (the nudge at building is
    `kb stop-check`'s, a separate command the harness joins). Anywhere else the news stays
    pending in `brief.md` and the next resume carries it (`house.resume_card`). The note
    comes first and the block is rewritten last, so a failure in between leaves the news
    pending rather than lost."""
    if (decision or card["stage"] not in NEWS_STAGES or card.get("blocked_reason")
            or views.rotating(card.get("options"))):
        return decision
    if tap_waiting(cfg, card):
        # c-604: his held tap goes first, so the news does not send the house back; it stays
        # pending in `brief.md` and the next resume carries it. The review gate and the
        # record check above still ran: they act on the staging turn and on no other.
        return None
    card_dir = cfg.cards_dir / card["id"]
    news = briefnews.news(card_dir, card, board.events(card["id"]))
    if not news:
        return None
    board.note(card["id"], f"told the house at its turn end: {news}", "hook")
    briefnews.refresh(card_dir, card)
    return {"decision": "block", "reason": news}


# ----- the hook body -----

def read_payload() -> dict:
    """The hook payload on stdin; empty, absent or unparsable stdin is an empty payload."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


def main(argv: list[str] | None = None) -> int:
    """`keel-turn-end <card>`: prints the decision, or nothing, and always exits 0."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("keel-turn-end needs a card id", file=sys.stderr)
        return 0
    payload = read_payload()
    board = None
    try:
        cfg = config_module.load()
        board = open_board(cfg)
        decision = check(cfg, board, argv[0], payload)
        if decision:
            print(json.dumps(decision))
        else:
            # The turn ends here: a tap held while it worked goes now (c-598, `keel/kick.py`).
            kick.after_stop(cfg, board.get(argv[0]))
    except Exception as error:  # noqa: BLE001 - a failing hook must not hold a house up
        print(f"keel-turn-end {argv[0]}: {error}", file=sys.stderr)
    finally:
        if board is not None:
            board.close()
    return 0
