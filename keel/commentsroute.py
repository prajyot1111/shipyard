"""A card's review comments page (c-643, docs/atlas/67-comments.md): `/comments/<id>` and its
data, `/api/comments/<id>`.

The page is served by the plan page's shell (`app/plan.html`, `PLAN_PAGE` takes `comments`),
so plan, outcome, CI and comments switch to each other from one header. Its data is what the
card pane read at shipping (`keel/shipreplies.py`), grouped by round: each item the house was
told, with its verdict, his choice and the words Ship would post. Nothing new is stored. A
comment cut on the card is read whole from the card's `comments/<file>` where this machine
keeps it (the drain that watches the pull request writes it), else the cut text is shown and
says so.
"""

from __future__ import annotations

import re
from datetime import datetime

from keel import shipreplies, shipwatch, terms

COMMENTS_API = re.compile(r"^/api/comments/(c-\d+)$")
CARD_KEYS = ("id", "title", "space", "stage", "repo", "output_ref", "blocked_reason", "session_id")


def told(card: dict) -> list[dict]:
    return list(shipreplies.shipping_of(card).get("told") or [])


def offered(card: dict) -> bool:
    """A card has a comments page at shipping, or once its house was ever told an item."""
    return card.get("stage") == "shipping" or bool(told(card))


CUT = shipwatch.CUT_MARK.split("{")[0]
NOT_HERE = "here"            # the whole text is on the machine that watches the pull request
EDITED = "edited"            # the comment was edited on the host after the house was told it


def whole_text(cfg, card: dict, item: dict) -> tuple[str, str | None]:
    """A comment's text, and why it is not whole (None when it is). A cut one is read from
    its file here, and only while that file is still the text the house was told: the
    watcher rewrites it when the comment is edited on the host (c-643 r1.F7)."""
    text = str(item.get("text") or "")
    if item.get("kind") != "comment" or CUT not in text:
        return text, None
    path = cfg.card_dir(card["id"]) / shipwatch.COMMENTS_DIR / shipwatch.comment_file(item.get("handle"))
    try:
        kept = path.read_text(errors="replace")
    except OSError:
        return text, NOT_HERE
    # the file is "# <handle>", a line of who and where, then the text as the host gave it
    parts = kept.split("\n\n", 2)
    whole = parts[2].rstrip("\n") if len(parts) == 3 else kept
    told = text[:text.index(CUT)].rstrip()
    return (whole, None) if whole.startswith(told) else (text, EDITED)


def rounds_of(cfg, found: list[dict], card: dict) -> list[dict]:
    """The rows grouped by the batch each item was told in, newest round first."""
    by: dict[int, dict] = {}
    for row in found:
        item = row["item"]
        text, why = whole_text(cfg, card, item)
        row = dict(row, text=text, whole=why is None, cut=why)
        batch = int(item.get("batch") or 0)
        found = by.setdefault(batch, {"round": batch, "told_at": item.get("told_at"), "rows": []})
        found["told_at"] = min(filter(None, (found["told_at"], item.get("told_at"))), default=None)
        found["rows"].append(row)
    return [by[key] for key in sorted(by, reverse=True)]


def in_turn(card: dict, rows: list[dict] | None) -> dict | None:
    """`{"working": True}` while the listing the deck already keeps (`rows`, c-653 review:
    never a harness call of this page's own) shows the card's house in a turn, by the one
    rule (`housejobs.working`); None otherwise, for a card that left shipping, and for a
    caller with no listing. The backend still holds the Ship itself."""
    if card.get("stage") != "shipping" or not rows:
        return None
    from keel import harness, housejobs     # noqa: PLC0415 - only a shipping card's page reads it
    return {"working": True} if housejobs.working(harness.find(card.get("session_id") or "", rows)) else None


def payload(cfg, board, card: dict, docs: list[str] | None, rows: list[dict] | None = None) -> tuple[int, dict]:
    """The page's answer. `docs` None: the caller already has the header's pages (a re-read
    on a board event), so they are not read again. `rows`: the deck's kept harness listing."""
    events = board.events(card["id"])
    card_out = {key: card.get(key) for key in CARD_KEYS}
    # what Ship's confirm reads: the shipping record without its told items (the rows are below)
    shipped = {key: value for key, value in shipreplies.shipping_of(card).items() if key != "told"}
    card_out["options"] = {"shipping": dict(shipped, told=[{"handle": i.get("handle")} for i in told(card)])}
    card_out["terms"] = terms.public(terms.of(cfg, card.get("space")))
    # c-653: the page draws Ship only where it can go, so it must know the house is in a turn
    card_out["house"] = in_turn(card, rows)
    # what the page's automatic-handling lines read, as the pane's do (c-655), and what he
    # sent back that the house has not been told yet (c-663)
    card_out["derived"] = {key: (card.get("derived") or {}).get(key) for key in ("ship_auto", "ship_handover", "ship_sendback", "ship_prepared", "archived")}
    found = shipreplies.rows(card, events) if offered(card) else []
    rounds = rounds_of(cfg, found, card)
    from keel import planroute     # noqa: PLC0415 - the plan route imports this module
    return 200, {"card": card_out, "docs": docs, "moves": planroute.moves_of(cfg, card),
                 "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "rounds": rounds,
                 # what Ship's confirm says (the pane reads the same from the card's detail)
                 "shipping": {"summary": shipreplies.summary(card, events, found)},
                 "why": None if offered(card) else f"{card['id']} has had no review to answer yet"}


class CommentsRoute:
    """Mixed into the deck's request handler, as the plan and CI routes are."""

    def kept_rows(self) -> list[dict] | None:
        """The harness listing the deck keeps (`Deck.listing`), or None when it cannot say."""
        try:
            with self.deck.lock:
                join = self.deck.listing()
            return join()
        except Exception:  # noqa: BLE001 - the page still reads; it only draws Ship as if idle
            return None

    def get_comments(self, card_id: str) -> None:
        from keel import ciroute      # noqa: PLC0415 - its docs list is the plan page's, plus CI
        # the header's pages read the plan, so a
        # re-read on a board event (`?again=1`) leaves them to the page (c-643 r1.F6)
        again = "again=1" in self.query()
        board = self.deck.board_factory()
        try:
            try:
                card = board.get(card_id)
            except Exception as error:      # noqa: BLE001 - an unknown card is a 404 with its reason
                return self.reply_json(404, {"error": str(error)})
            status, body = payload(self.cfg, board, card, None if again else ciroute.docs_of(self.cfg, card),
                                   rows=self.kept_rows())
        finally:
            board.close()
        self.reply_json(status, body)
