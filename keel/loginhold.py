"""The drain's houses held for a space's expired login: blocked with one reason, marked as
the drain's own, and put back once the login works again.

`keel/login.py` says whether a space's login works. This module is what the drain does on
the card when it does not (lane Q, 2026-09-24):

- `hold` blocks the card with `login.block_reason`, so it shows under needs-you with the one
  command that fixes it. Before the block it sets `options.login_hold` to the space, and
  that `set` event directly before the drain's `block` is the MARKER. It is how
  `held_space` knows the block is this rule's, without reading the reason's prose.
- `held_space` answers the space only while that is still the whole story: the card is
  blocked, and walking its block and unblock events and the `set` events that touch
  `options.login_hold` newest first, the first is a `block` by the drain and the next is
  the `set` that marked it. A `set` of any other option is not the hold's business and is
  passed over: the block's own drop of a re-offer ask and a voice hold taken since both
  record one (c-651), and neither says anything about the login. His unblock, his own
  block, or any later block of the drain's for another reason comes first, and the answer
  is None: a card he unblocked or blocked himself is never touched, and neither is one the
  drain blocked since for something else.
- `restore` resumes the card once, through the usual `house.resume` path with its own
  prompt, and only then unblocks it and clears the marker, with a note. A resume that fails
  leaves it blocked, with the failure noted, for him.
- `release` is `restore` without the house, for a card Bosun builds (c-647): the block and
  the marker go, with a note, and nothing is resumed.
"""

from keel import house, login
from keel.config import Config

HOLD_OPTION = "login_hold"
RESUME_PROMPT = ("your turn ended because this space's login had expired, and it works "
                 "again now. Carry on from where you stopped and take the card to its gate; "
                 "it is still at {stage}.")
MARK_KINDS = ("block", "unblock", "set")


def hold(cfg: Config, board, card: dict, space: str) -> str:
    """Mark, then block, with the one plain reason; returns the reason."""
    reason = login.block_reason(space, cfg.spaces[space].config_dir)
    if (board.get(card["id"]).get("options") or {}).get(HOLD_OPTION):
        # A marker left from a hold he answered himself: a `set` to the same value records
        # no event, and the event is the marker, so it is cleared first.
        board.set_fields(card["id"], {"options": {HOLD_OPTION: None}}, "drain")
    board.set_fields(card["id"], {"options": {HOLD_OPTION: space}}, "drain")
    board.block(card["id"], reason, "drain")
    return reason


def marks(event: dict, space: str) -> bool:
    """A `set` event that put `options.login_hold` to this space."""
    options = (event.get("data") or {}).get("options") or {}
    return event["kind"] == "set" and options.get(HOLD_OPTION) == space


def counts(event: dict) -> bool:
    """A block or an unblock, or a `set` that touched `options.login_hold` (to any value)."""
    if event["kind"] not in MARK_KINDS:
        return False
    return event["kind"] != "set" or HOLD_OPTION in ((event.get("data") or {}).get("options") or {})


def held_space(board, card: dict) -> str | None:
    """The space whose login this card is blocked for, by the drain, still; else None."""
    space = (card.get("options") or {}).get(HOLD_OPTION)
    if not card.get("blocked_reason") or not space:
        return None
    relevant = [event for event in board.events(card["id"]) if counts(event)]
    if len(relevant) < 2:
        return None
    block, before = relevant[-1], relevant[-2]
    if block["kind"] != "block" or block["actor"] != "drain" or not marks(before, space):
        return None
    return space


def restore(cfg: Config, board, card: dict, space: str) -> bool:
    """Resume the held card once and unblock it; False (and a note) when the resume fails."""
    try:
        house.resume(cfg, board, card["id"], prompt=RESUME_PROMPT.format(stage=card["stage"]))
    except Exception as error:  # noqa: BLE001 - one bad card must not stop the pass
        board.note(card["id"], f"the {space} login works again, but resuming this house "
                               f"failed on {cfg.host}: {error}", "drain")
        return False
    board.unblock(card["id"], "drain")
    board.set_fields(card["id"], {"options": {HOLD_OPTION: None}}, "drain")
    board.note(card["id"], f"the {space} login works again; the drain resumed this house "
                           f"and took its login block off", "drain")
    return True


def release(board, card: dict, space: str) -> None:
    """Take the login block and its marker off a card Bosun builds; no house is resumed."""
    board.unblock(card["id"], "drain")
    board.set_fields(card["id"], {"options": {HOLD_OPTION: None}}, "drain")
    board.note(card["id"], f"the {space} login works again; the drain took its login block "
                           f"off. Bosun builds this card, so no house was resumed", "drain")
