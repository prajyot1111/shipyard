"""Where a board is used, asked before he deletes it (BD-2, lane BD, 2026-09-24).

The deck's confirm says it plainly: "b-006 is embedded in c-272's outcome. Delete anyway?"
So before a delete the page asks `GET /api/boards/uses?ids=b-006`, and this reads the plan and
the outcome of every open card and every card touched in the last `RECENT_DAYS` days for a
```board block naming that id, parsed by the plan format's own parser so an id is spelled
the way the store spells it.
"""

from datetime import datetime, timedelta, timezone

from keel import planformat, planroute

RECENT_DAYS = 14
DOCS = ("plan", "outcome")


def recent(card: dict, now: datetime) -> bool:
    """Open, or touched in the last `RECENT_DAYS` days; never an archived card."""
    if (card.get("derived") or {}).get("archived"):
        return False
    if card.get("stage") != "done":
        return True
    try:
        touched = datetime.fromisoformat(card.get("updated_at") or "")
    except (TypeError, ValueError):
        return False
    if touched.tzinfo is None:
        touched = touched.replace(tzinfo=timezone.utc)
    return now - touched <= timedelta(days=RECENT_DAYS)


def refs_in(cfg, card: dict, doc: str) -> set[str]:
    """The board ids one document embeds, as the store spells them."""
    try:
        text, name, _base, _why = planroute.source(cfg, card, doc)
    except OSError:
        return set()
    if not text:
        return set()
    parsed = planformat.parse(text, name)
    return {block["ref"] for block in planformat.all_blocks(parsed["blocks"])
            if block["type"] == "board" and block.get("ref")}


def uses(cfg, board, board_ids: list[str]) -> dict:
    """{uses: {board id: [{card, title, doc, stage}]}}."""
    wanted = {str(board_id): [] for board_id in board_ids}
    now = datetime.now(timezone.utc)
    for card in board.list_cards(include_archived=False):
        if not recent(card, now):
            continue
        for doc in DOCS:
            for ref in refs_in(cfg, card, doc) & set(wanted):
                wanted[ref].append({"card": card["id"], "title": card.get("title") or "",
                                    "doc": doc, "stage": card.get("stage") or ""})
    return {"uses": wanted}
