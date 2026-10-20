"""Import Harbor's card ledger into the board.

Harbor's `ledger/cards.jsonl` is append-only: `card.create`, `card.set` and `card.note`
events. Folding is last-value-per-field with notes kept in order. Each Harbor card becomes
one board card with its original id and `created_at`; the fields the board does not have
go into `options`; notes become `note` events at their original time. A card that already
exists is skipped, so a second run changes nothing.
"""

import json
from pathlib import Path

from keel.board import AUTONOMY, Board

LEDGER = Path("ledger") / "cards.jsonl"     # under `[machine] harbor_dir`
STAGE_MAP = {"checking": "building"}
OPTION_KEYS = ("tracker_ref", "tracker_mode", "base", "rich_story", "design_doc",
               "design_doc_url", "link_doc", "include_tests", "test_doc", "test_doc_url",
               "model_strategy", "plan_style", "guidance", "branch", "worktree", "tmux",
               "archived")


def fold(ledger: Path) -> dict[str, dict]:
    """Replay the ledger into {id: {space, created_at, updated_at, fields, notes}}."""
    cards: dict[str, dict] = {}
    with open(ledger, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                _apply(cards, json.loads(line))
    return cards


def _apply(cards: dict, event: dict) -> None:
    verb, card_id, at = event.get("verb"), event.get("card"), event.get("at")
    if verb == "card.create" and card_id not in cards:
        cards[card_id] = {"space": event.get("space"), "created_at": at, "fields": {}, "notes": []}
    card = cards.get(card_id)
    if card is None:
        return
    if verb in ("card.create", "card.set"):
        card["fields"].update(event.get("fields") or {})
    elif verb == "card.note":
        card["notes"].append({"at": at, "text": event.get("text") or "", "by": event.get("by")})
    card["updated_at"] = at


def _stage(fields: dict) -> str:
    stage = fields.get("stage")
    if stage is None:
        return "done" if fields.get("done_at") else "inbox"
    return STAGE_MAP.get(stage, stage)


def _autonomy(fields: dict) -> str:
    value = fields.get("autonomy")
    return value if value in AUTONOMY else "autonomous"


def _options(fields: dict) -> dict:
    return {key: fields[key] for key in OPTION_KEYS if fields.get(key) is not None}


def to_row(card_id: str, folded: dict) -> dict:
    fields = folded["fields"]
    return {
        "id": card_id,
        "space": folded["space"],
        "title": fields.get("title") or card_id,
        "brief": fields.get("description") or "",
        "autonomy": _autonomy(fields),
        "repo": fields.get("repo") or None,
        "model": fields.get("model") or None,
        "stage": _stage(fields),
        "blocked_reason": fields.get("blocked_reason") or None,
        "session_id": fields.get("session_id") or None,
        "plan_ref": fields.get("plan_ref") or None,
        "output_ref": fields.get("pr") or fields.get("output_ref") or None,
        "parent": None,
        "after": None,
        "options": _options(fields),
        "created_at": folded["created_at"],
        "updated_at": folded.get("updated_at") or folded["created_at"],
    }


def import_ledger(board: Board, ledger: Path, skip_archived: bool = False) -> dict:
    """Import every card not already on the board; return the counts."""
    counts = {"imported": 0, "notes": 0, "existing": 0, "archived_skipped": 0, "by_space": {}}
    for card_id, folded in fold(Path(ledger).expanduser()).items():
        if board.exists(card_id):
            counts["existing"] += 1
            continue
        row = to_row(card_id, folded)
        if skip_archived and row["options"].get("archived") is True:
            counts["archived_skipped"] += 1
            continue
        _import_one(board, row, folded["notes"])
        counts["imported"] += 1
        counts["notes"] += len(folded["notes"])
        counts["by_space"][row["space"]] = counts["by_space"].get(row["space"], 0) + 1
    return counts


def _import_one(board: Board, row: dict, notes: list[dict]) -> None:
    with board.tx():
        board.insert_card(row, "import")
        for note in notes:
            board.record_event(row["id"], "note", "import", text=note["text"],
                               data={"by": note["by"]}, at=note["at"])


def summary(counts: dict) -> str:
    spaces = ", ".join(f"{n} {space}" for space, n in sorted(counts["by_space"].items()))
    return (f"imported {counts['imported']} cards ({spaces or 'none'}) with {counts['notes']} notes; "
            f"skipped {counts['existing']} already present, {counts['archived_skipped']} archived")
