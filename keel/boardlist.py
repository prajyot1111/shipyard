"""The deck's board list: every board with the card it belongs to, and one search.

C5 of the overnight clearance (2026-09-23, card c-447). B12 split the Saved list into Houses
and Harbor; with tens of boards per card that list became a wall of rows. So a house's boards
are grouped by CARD on the page, which needs each row to carry its card's title and its
tracker story id, and Harbor's by topic (`boards.topic_key`). And one search box looks
across board titles, node labels, what the attachments say, the card id, the card title
and the story id; a hit carries the matching snippet and the node it is on, so the page
opens the board with that node lit.

ONE STORE. The search reads the board files directly (`board.json` and `ops.log`, folded
through the same `boards.build` the deck folds), and the card fields come from the board
database. There is no index to keep in agreement with either: the corpus is his own boards,
tens of them, and reading them whole is milliseconds.
"""

import re

from keel import boards, boardtrash

SNIPPET = 120
WORD = re.compile(r"[\w.-]+", re.U)


def cards_of(cfg, ids: set[str]) -> dict:
    """{card id: {title, story, space, review, done}} for the cards these boards belong to.
    `review` marks a review card's board (lane FC, FC-4): it describes a colleague's code, and
    the deck's list leaves it out until he includes it. `done` marks a card that is finished,
    at stage done or archived (c-562): the list leaves its boards out until Include done."""
    if not ids:
        return {}
    out = {}
    try:
        from keel.board import open_board
        board = open_board(cfg)
    except Exception:  # noqa: BLE001 - a list without titles is still a list
        return {}
    try:
        for card_id in ids:
            try:
                card = board.get(card_id)
            except Exception:  # noqa: BLE001 - a card that is gone keeps its id
                continue
            options = card.get("options") or {}
            out[card_id] = {"title": card.get("title") or "", "space": card.get("space") or "",
                            "story": str(options.get("tracker_ref") or ""),
                            "review": bool(options.get("review_key")),
                            "done": card.get("stage") == "done" or options.get("archived") is True}
    finally:
        board.close()
    return out


def attachment_text(item: dict) -> str:
    """What an attachment says, as one line of text to search."""
    parts = [item.get("text"), item.get("title"), item.get("path"), item.get("lang")]
    parts += list(item.get("cols") or [])
    for row in item.get("rows") or []:
        parts += list(row)
    parts += list(item.get("lines") or [])
    return " ".join(str(part) for part in parts if part)


def places(cfg, row: dict) -> list[tuple[str, str, str | None]]:
    """(field, text, node id) for everything on one board a search may match, in the
    order a hit is reported: the title, the node labels, the attachments, the card."""
    out = [("title", row.get("title") or "", None)]
    try:
        model = boards.build(boards.ops_lines(cfg, row["id"]))
    except Exception:  # noqa: BLE001 - a board that will not fold is still listed
        model = boards.new_model()
    for node in model["nodes"]:
        out.append(("label", " ".join(filter(None, [node.get("label"), node.get("sub")])),
                    node["id"]))
    node_ids = {node["id"] for node in model["nodes"]}
    for item in model["attachments"]:
        at = item.get("at")
        out.append(("attachment", attachment_text(item), at if at in node_ids else None))
    card = row.get("card") or {}
    source = row.get("source") or {}
    out += [("card", str(source.get("card") or ""), None),
            ("card title", card.get("title") or "", None),
            ("story", card.get("story") or "", None)]
    return [place for place in out if place[1]]


def snippet(text: str, word: str) -> str:
    """The part of `text` around the first place `word` is, clipped to `SNIPPET`."""
    at = text.lower().find(word)
    if len(text) <= SNIPPET or at < 0:
        return text[:SNIPPET]
    start = max(0, at - SNIPPET // 3)
    return ("..." if start else "") + text[start:start + SNIPPET].strip() + "..."


def hit_of(cfg, row: dict, words: list[str]) -> dict | None:
    """The board's best match for every word, or None when a word is found nowhere.

    Every word must be somewhere on the board; the place REPORTED is the one holding the
    most of them, because that is the line he is most likely to have been remembering; on a
    tie a place ON A NODE wins, because a hit on a node opens the board with it lit."""
    found = places(cfg, row)
    everything = " ".join(text.lower() for _field, text, _node in found)
    if not all(word in everything for word in words):
        return None
    best = max(found, key=lambda place: (sum(word in place[1].lower() for word in words),
                                         place[2] is not None))
    first = next((word for word in words if word in best[1].lower()), words[0])
    return {"field": best[0], "snippet": snippet(best[1], first), "node": best[2]}


def listing(cfg, query: str = "", deleted: bool = False) -> dict:
    """`GET /api/boards[?q=...][&deleted=1]`: every board with its card, and the hits for
    `query`. `deleted` reads the trash instead (BD-3's trash, which the deck's Include deleted adds), searched the same way."""
    rows = boardtrash.trashed(cfg) if deleted else boards.listing(cfg)
    ids = {str((row.get("source") or {}).get("card")) for row in rows
           if (row.get("source") or {}).get("card")}
    cards = cards_of(cfg, ids)
    for row in rows:
        card_id = (row.get("source") or {}).get("card")
        row["card"] = cards.get(card_id) if card_id else None
        row["topic"] = boards.topic_key(row.get("title") or "")
    words = [word.lower() for word in WORD.findall(str(query or ""))]
    if not words:
        return {"rows": rows, "query": ""}
    matched = []
    for row in rows:
        hit = hit_of(cfg, row, words)
        if hit is not None:
            matched.append(dict(row, hit=hit))
    return {"rows": matched, "query": " ".join(words)}
