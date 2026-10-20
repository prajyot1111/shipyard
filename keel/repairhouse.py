"""Bosun's house repairs, carried to the house (c-575; c-593; docs/atlas/96-bosun.md, "Repairs").

`kb console resume <card> --why` and `kb console retry <card> --why`, on a card in any
space whose standing block Keel wrote (`repair.refuse_unless_mechanics`). The repair is
recorded first (`Board.repair`, the why on the card), then carried out as his tap would be,
on this machine, where every house is. The house hears the plain resume line and nothing of
Bosun's (`repair.refuse_words`, his D3).

These were two of the driven-card verbs (`keel/drive.py`, c-522) until c-593 retired
driving; only their repair form is left, so `--why` is required.

It is an authority path (`authority.AUTHORITY_PATHS`): it decides what reaches a house.
"""

from keel import authority, house, prompts, repair
from keel.board import Board, Refused
from keel.config import Config

SUBS = ("resume", "retry")
USAGE = "resume <card> --why <what broke> | retry <card> --why <what broke>"


def refuse_busy(cfg: Config, card: dict) -> None:
    """A repair resumes only an idle or blocked house: a working one is refused before the
    repair is recorded (the harness's own refusal would come after it)."""
    if not card.get("session_id"):
        return
    space = cfg.spaces.get(card["space"])
    if space is None:
        raise Refused(f"{card['space']} is not configured on {cfg.host}, so whether "
                      f"{card['id']}'s house is working cannot be read here")
    try:
        house.refuse_if_busy(card, space.config_dir)
    except Refused:
        raise
    except Exception as error:      # noqa: BLE001 - its own refusal, whatever it is called
        raise Refused(str(error)) from None


def resume(cfg: Config, board: Board, card_id: str, actor: str, why: str,
           words: str = "") -> dict:
    """Resume a house whose block Keel wrote: no words at all, so nothing Bosun writes
    reaches a house."""
    card = board.get(card_id)
    repair.refuse_words(words)
    if not card.get("session_id"):
        raise Refused(f"{card_id} has no house session to resume; retry it instead")
    refuse_busy(cfg, card)
    board.repair(card_id, "resume", actor, why, words)
    prompt = prompts.RESUME.format(stage=card["stage"])
    try:
        result = house.resume(cfg, board, card_id, prompt=prompt, actor=actor)
    except Refused:
        # Refused, not failed: the house became busy or held since the check. Nothing moved
        # and the card stays as it was (the repair is recorded, as his tap's would be).
        raise
    except Exception as error:      # noqa: BLE001 - whatever stopped it, the card says so
        # A resume that did not happen leaves the card blocked, marked as a failed resume,
        # so it shows as his and stays repairable, rather than unblocked with nothing moving.
        said = (str(error).splitlines() or [type(error).__name__])[0]
        board.block(card_id, f"Bosun's resume failed: {said}"
                    + (f"\n(it was blocked: {card['blocked_reason']})" if card["blocked_reason"] else ""),
                    actor, mark="failed-resume")
        raise Refused(f"the resume of {card_id} failed ({said}); the card is blocked, marked "
                      f"as a failed resume") from None
    if card["blocked_reason"]:
        board.unblock(card_id, actor, counted=False, expect=card["blocked_reason"])
    return result


def retry(cfg: Config, board: Board, card_id: str, actor: str, why: str) -> dict:
    """A fresh house: back to assigned for the drain to start."""
    card = board.get(card_id)
    authority.refuse_retry(card)
    refuse_busy(cfg, card)
    board.repair(card_id, "retry", actor, why)
    board.restart_card(card_id, actor)
    return {"assigned": card_id, "note": "the drain starts it on its next pass"}


# ----- the kb verb -----

def command(board: Board, args, actor: str, target) -> dict:
    cfg = args.config
    sub = args.sub
    card_id = target("<card>")
    why = getattr(args, "why", None)
    if actor != authority.BOSUN:
        raise Refused(f"kb console {sub} is Bosun's repair; he acts on a house from the deck")
    if why is None:
        raise Refused(f"kb console {sub} is a repair: say what broke with --why \"<what broke>\"")
    repair.refuse_why(actor, why)
    if sub == "resume":
        done = resume(cfg, board, card_id, actor, why, args.words or "")
        return {"card": card_id, "resumed": _jsonable(done)}
    return {"card": card_id, "retried": retry(cfg, board, card_id, actor, why)}


def _jsonable(result) -> dict:
    return {k: v for k, v in (result or {}).items() if isinstance(v, (str, int, bool, type(None)))}


def render(args, payload) -> str:
    return f"{args.sub} {payload['card']}: repaired"
