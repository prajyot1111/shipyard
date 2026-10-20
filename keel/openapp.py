"""Resume and open in app (V2-2): the house back WITHOUT a turn, and its current link.

He wants to type into a house in the Claude app, and a resume would put a "continue" turn
in first (2026-09-24). So an exited house is WOKEN (`house.wake`: no prompt, no model turn,
the same session and the same claude.ai link) and a listed one is left exactly as it is.
A house whose conversation the harness no longer holds cannot be woken (c-654): it is started
afresh from the card's record (`afresh.here`) and its new link is the one returned; on a
done card, whose house is never started again, the tap is refused in plain words instead.
A house in its turn is neither woken nor refused (c-653): nothing is started, and its
link is read from its log so he has a way into it. Otherwise it is refused wherever a resume
is (`house.refuse_if_busy`: a session open in his terminal, a Drop in hold), under the card's
lock like every start. The deck's
verb is `house.open_app` (`keel/actions.py`), which returns the link for the page to open.
"""

from keel import adapters, afresh, harness, house, housejobs, prompts
from keel.board import Board, Refused
from keel.config import Config

# The log prints the link a few seconds after a start; a tap waits this many seconds for it
# at most, where a start waits `house.APP_LINK_TRIES`.
APP_OPEN_TRIES = 4


def open_for_app(cfg: Config, board: Board, card_id: str) -> dict:
    """{"woken": bool, "link": str | None}. The link is the one the card's CURRENT session
    recorded (`current_link`), else polled from the log for a few seconds and kept on the
    card; None when the log has not printed one yet, and the house stays up either way."""
    with house.card_lock(cfg, card_id):
        card = board.get(card_id)
        if not card.get("session_id"):
            raise Refused(f"{card_id} has no house session to open; use Retry")
        space = adapters.space_of(cfg, card)
        row = harness.find(card["session_id"], harness.agents(space.config_dir))
        if housejobs.working(row):
            # c-653: a house in its turn is left exactly as it is; only its link is read
            # (c-135 was answering review with no link on record and no way in)
            house.refuse_if_in_terminal(card, row)
            woken = None
        else:
            house.refuse_if_busy(card, space.config_dir)
            # c-654: a wake of a conversation the harness no longer holds launches and then
            # fails with no turn, so that house is started afresh from the card's record instead
            woken = (afresh.here(cfg, board, card, prompts.JOIN_AFRESH)
                     or house.wake(cfg, board, card_id))
        card = board.get(card_id)
        link = current_link(board, card)
        if not link:
            bg_id = (woken or {}).get("bg_id") or (row or {}).get("id") or card["session_id"][:8]
            link = house.app_link(bg_id, space.config_dir, tries=APP_OPEN_TRIES)
            if link:
                board.set_fields(card_id, {"options": {"app_link": link}}, "serve")
        return {"woken": woken is not None, "link": link}


def current_link(board: Board, card: dict) -> str | None:
    """The claude.ai link of the session the card is on NOW, or None.

    `options.app_link` alone cannot say it: a resume that found no link records its new
    session and keeps the old one's link, which opens a conversation the card has left. So
    the events are read newest first back to the `session` event that recorded the current
    session; a link set on the way, or carried by that event, is the current one."""
    for event in reversed(board.events(card["id"])):
        data = event["data"] or {}
        if event["kind"] == "set" and (data.get("options") or {}).get("app_link"):
            return data["options"]["app_link"]
        if event["kind"] == "session":
            return data.get("app_link") if data.get("session_id") == card["session_id"] else None
    return None
