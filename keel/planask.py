"""`plan.ask`: a question he wants cleared WITHOUT sending the plan back (P2-9).

Beside Note, the plan page offers Ask on any block or selection. It does not wait for Send:
the question is recorded as his `ask` mark on the card (`keel/planstate.py`) and the house is
resumed at once, with a prompt that
forbids revising the plan and moving the card (`prompts.plan_ask`). The house answers with
`kb reply <card> --ask <id> --text ...` (`Board.reply`), a `reply` event tied to the mark,
and the event stream's `card <id>` reloads the page, which pins the answer under his
question. The card stays at its gate, the plan file is untouched, and his other answers and
notes stay pending for the final Send. This replaces Send back and stay on the plan pages.

An idle house is TOLD the question in its own session (`keel/tellhouse.py`, c-598), and an
exited one is resumed. A WORKING house is not interrupted: while an earlier question is still
open the house is presumably answering it, so the new one is recorded and not sent, and `kb
reply` hands the house the next open question with its answer (asks in a row QUEUE); with no
earlier question open, the ask is HELD as a resume relay on the card, which the
drain tells the house when its turn ends (`hold`, the deck's `hold_here`). A session open in
his terminal is still refused. A house that ended its turn without answering is told every
open question, in order.

It takes the deck's verbs as arguments rather than importing `keel/actions.py`, which
imports this module to put `plan.ask` in its table.
"""

from __future__ import annotations

import json

from keel import house, planstate, prompts
from keel.board import Refused

DOCS = {"plan": "plan", "outcome": "outcome"}


class AskError(Exception):
    pass


def ask(cfg, board, body: dict, *, run_kb, gate_of, hold=None) -> dict:
    card = board.get(str(body.get("id") or ""))
    doc = body.get("doc") or "plan"
    if doc not in DOCS:
        raise AskError(f"a question is on the plan or the outcome, not {doc!r}")
    if gate_of(card) != DOCS[doc]:
        raise AskError(f"{card['id']} has no {doc} gate open to ask about (it is at {card['stage']})")
    if not card.get("session_id"):
        raise AskError(f"{card['id']} has no house session to ask")
    text = str(body.get("text") or "").strip()
    if not text:
        raise AskError("a question asks something")
    waiting = planstate.open_asks(board.events(card["id"]), doc)
    busy = working(cfg, card, waiting, can_hold=hold is not None)
    queued = busy == QUEUE
    mark = {"what": "ask", "doc": doc, "block": body.get("block") or None,
            "quote": body.get("quote") or None, "text": text}
    event = (run_kb(cfg, ["mark", card["id"], "--data=" + json.dumps(mark)]) or {}).get("event")
    if queued:
        return {"asked": event, "queued": True,
                "note": "asked; the house answers it after the question before it"}
    prompt = prompts.plan_ask(card["id"], planstate.open_asks(board.events(card["id"]), doc), doc)
    if busy == HOLD:
        return dict(hold(cfg, card, prompt), asked=event, queued=False, prompt=prompt)
    try:
        resumed = house.resume(cfg, board, card["id"], prompt=prompt, tell=True, background=True)
    except house.Busy as refusal:
        if hold is None or isinstance(refusal, house.InTerminal):
            raise AskError(f"the question is on the card, but {refusal}") from None
        return dict(hold(cfg, card, prompt), asked=event, queued=False, prompt=prompt)
    except Refused as refusal:
        raise AskError(f"the question is on the card, but {refusal}") from None
    return {"asked": event, "queued": False, "resumed": resumed, "prompt": prompt,
            "note": (resumed or {}).get("note") or "asked; the answer shows under your question"}


QUEUE, HOLD = "queue", "hold"


def working(cfg, card: dict, waiting: list[dict], can_hold: bool = True) -> str | None:
    """`QUEUE` when the house is working on an earlier question (the new one waits for `kb
    reply`), `HOLD` when it is working on anything else (the ask is told at its turn's end),
    None when it is not working. A session open in his terminal refuses the ask, and so does
    a working one when the caller has no way to hold it."""
    space = cfg.spaces.get(card["space"])
    try:
        house.refuse_if_busy(card, space.config_dir if space else None)
    except house.InTerminal as refusal:
        raise AskError(str(refusal)) from None
    except house.Busy as busy:
        if waiting:
            return QUEUE
        if not can_hold:
            raise AskError(str(busy)) from None
        return HOLD
    except Refused as refusal:
        raise AskError(str(refusal)) from None
    return None
