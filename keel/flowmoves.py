"""A move you make on a card (c-640): the owner's tap on a move of the space's flow that is
theirs (`by = "you"`) tells the card's house what to do, and records it.

`flow.move` {id, move}: the move must be in the card's space flow, the owner's, and offered
at the card's stage (`flows.offered`). The card gets a `flow` note naming it and
`options.flow_move = {id, pushes, opens, names, labels, stages, at}`, which `kb flowpush`
(`keel/flowfence.py`, c-641) reads to let that move push only to the branches it names and
open only the changes it names. The house is then told the move's prompt the way Resume
tells it (`actions.act_resume`): told in place when idle, resumed when it has exited, held
for its turn's end when working, relayed to the machine it runs on. It is the owner's tap
only: a house's own `kb` cannot make a move (`actions.act`, the HOUSE_VERBS belt).

A move that `pushes` is refused while a shipping card's record says its worktree is behind
its change's branch or has diverged from it (`options.shipping.local`, read only, c-664):
the house would push that old history to a shared branch. Only at shipping, where the drain
keeps that record fresh.
"""

from __future__ import annotations

from datetime import datetime

from keel import flows

VERB = "flow.move"
OPTION = "flow_move"
OUT_OF_STEP = "The branch is out of step with what was pushed."
HELD = "{label} is held: {said} A flow move must not push old history to a shared branch."


class MoveError(Exception):
    """A move that is not the owner's to make on this card now."""


def move_of(cfg, card: dict, move_id: str) -> flows.Move:
    space = cfg.spaces.get(card.get("space") or "")
    if space is None:
        raise MoveError(f"{card['id']}'s space is not configured here")
    found = flows.of(cfg, space)
    move = found.move(move_id)
    if move is None:
        raise MoveError(f"the {space.name} flow ({found.name}) has no move {move_id!r}")
    if not move.yours:
        raise MoveError(f"{move.label} is made by {move.by}, not by a tap")
    if card.get("stage") not in move.stages:
        raise MoveError(f"{move.label} is offered at {', '.join(move.stages)}; "
                        f"{card['id']} is at {card.get('stage')}")
    if not flows.based(move, card, cfg):
        raise MoveError(f"{move.label} is for a card based on {', '.join(move.bases)}; "
                        f"{card['id']} is based on {(card.get('options') or {}).get('base') or 'no named base'}")
    if card.get("blocked_reason"):
        raise MoveError(f"{card['id']} is blocked; answer it first")
    astray = out_of_step(card) if move.pushes else None
    if astray:
        raise MoveError(HELD.format(label=move.label, said=astray))
    return move


def out_of_step(card: dict) -> str | None:
    """The shipping record's own sentence while a SHIPPING card's worktree is behind its
    change's branch or has diverged from it (`shipping.local_facts`: `said`), or None: the
    worktree is in step, or the card is at another stage. The record is believed only at
    shipping, where the drain keeps it fresh: no stage move drops it, so one left on a card
    that went back to building or review says nothing about its branch now."""
    local = ((card.get("options") or {}).get("shipping") or {}).get("local") or {}
    if card.get("stage") != "shipping" or not (local.get("behind") or local.get("diverged")):
        return None
    return str(local.get("said") or OUT_OF_STEP)


def facts(cfg, card: dict, move: flows.Move | None, found: flows.Flow) -> dict:
    """The card's base (`house.target_of`: its options.base, its integration branch, or its
    checkout's), its branch (options.branch once a change exists, else the branch its
    outcome names), and the move's target with `{base}` filled. A fact that cannot be read
    stays unfilled in the prompt, which says so to the house rather than an empty word."""
    from keel import house, merging     # noqa: PLC0415 - only a tap reads them
    options = card.get("options") or {}
    try:
        base = house.target_of(cfg, card) if card.get("repo") else str(options.get("base") or "")
    except (OSError, merging.MergeRefused, IndexError, AttributeError):
        base = str(options.get("base") or "")
    branch = str(options.get("branch") or merging.named_branch(card) or "")
    target = name_of(found, move.target, base, branch) if move is not None else ""
    return {"base": base, "branch": branch, "target": target}


def name_of(found: flows.Flow, branch_id: str, base: str, branch: str) -> str:
    """A flow branch's git name for this card: its label with `{base}` and `{branch}` filled
    (an environment branch, the base, `feature/x-main`); a fact it cannot read stays
    as written."""
    label = next((one.label for one in found.branches if one.id == branch_id), branch_id)
    if base:
        label = label.replace("{base}", base)
    return label.replace("{branch}", branch) if branch else label


def names_of(found: flows.Flow, ids, known: dict) -> dict[str, str]:
    """The git name of each flow branch in `ids`, from `found` and the card's facts."""
    return {one: name_of(found, one, known["base"], known["branch"]) for one in ids}


def labels_of(found: flows.Flow, ids) -> dict[str, str]:
    """What the FLOW calls each branch in `ids`: its label as written, `{base}` and all."""
    said = {one.id: one.label for one in found.branches}
    return {one: said.get(one, one) for one in ids}


def prompt(cfg, card: dict, move: flows.Move) -> str:
    found = flows.of(cfg, cfg.spaces[card["space"]])
    said = flows.prompt_for(move, card, **facts(cfg, card, move, found))
    return (f"You are asked for a move of this space's flow: {move.label} ({move.id}).\n\n{said}\n\n"
            f"When it is done, say on the card what you did (`kb note {card['id']} ...`), "
            f"then end your turn.")


def grant(cfg, board, card: dict, move: flows.Move) -> None:
    """The grant a fence reads (c-641): the owner's tap's, and only theirs
    (`HUMAN_ONLY_OPTIONS`). It carries the git name of each branch the move may push or
    open, filled here at the tap from the flow that granted it, so the pack and a house on
    the other machine read the same names (c-641 review). `labels` is what the flow called
    those branches at the tap: a flow that calls one differently later ends the grant
    (`flowfence.info`, c-664), and nothing else about the card does."""
    found = flows.of(cfg, cfg.spaces[card["space"]])
    ids = (*move.pushes, *move.opens)
    names = names_of(found, ids, facts(cfg, card, None, found))
    at = datetime.now().astimezone().isoformat(timespec="seconds")
    board.set_fields(card["id"], {"options": {OPTION: {"id": move.id, "pushes": list(move.pushes),
                                                       "opens": list(move.opens), "names": names,
                                                       "labels": labels_of(found, ids),
                                                       "stages": list(move.stages), "at": at}}}, "human")


def revoke(board, card: dict) -> None:
    """A tap whose tell failed: the grant the card had before it (`card` as read before the
    tap), or none."""
    board.set_fields(card["id"], {"options": {OPTION: (card.get("options") or {}).get(OPTION)}}, "human")


def asked(board, card: dict, move: flows.Move) -> None:
    board.note(card["id"], f"flow move asked: {move.label} ({move.id})", "human")
