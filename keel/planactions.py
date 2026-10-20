"""`plan.send`: one tap that carries his whole round on a plan page to the house.

The page records each answer and note as it is made (`kb mark`, `keel/planstate.py`); this
verb composes the round into one text ON THE SERVER, so the page never writes the prompt a
house reads (F-3), and hands it to the gate verbs that already exist: Approve quotes it as
his words, Send back uses it as the reason. Nothing new resumes a house and nothing polls.
Then a `sent` mark closes the round, so the next revision starts clean and the lint can
refuse a decision left open that he already answered (C16).

A gate is answered once (c-537, `keel/receipt.py`): a send at a gate the receipt says was
answered is refused, except Approve again after a refused landing, which first clears that
refusal's block (`kb unblock --expect`, so no other block is ever cleared by it).

It takes the gate verbs as arguments rather than importing `keel/actions.py`, which imports
this module to put `plan.send` in its table.
"""

from __future__ import annotations

import json
from pathlib import Path

from keel import artifacts, deckstate, planformat, planstate, receipt, terms

MODES = ("approve", "sendback")


class SendError(Exception):
    pass


def plan_text(cfg, card: dict, doc_name: str = "plan") -> tuple[str, str | None]:
    """The WHOLE document. The pane's preview (`deckstate.card_files`) is cut at
    `deckstate.PLAN_TEXT_MAX`, which is right for a preview and wrong for a send that
    composes every decision: a long plan lost its last sections."""
    if doc_name == "outcome":
        return deckstate.card_files(cfg, card).get("context") or "", None
    ref = card.get("plan_ref") or ""
    if ref and not ref.startswith("http"):
        path = artifacts.local_path(ref, cfg.root)
        return (path.read_text(errors="replace"), None) if path.is_file() else ("", "no plan file at " + ref)
    return "", "this card has no plan file"


def document(cfg, card: dict, doc_name: str) -> dict:
    refs = terms.refs(terms.of(cfg, card.get("space")))      # the card's own refs (c-630)
    if doc_name == "outcome":
        return planformat.parse(plan_text(cfg, card, "outcome")[0], "context.md", refs)
    text, away = plan_text(cfg, card)
    if not text:
        raise SendError(away or f"{card['id']} has no markdown plan to answer on")
    return planformat.parse(text, Path(card.get("plan_ref") or "plan.md").name, refs)


def send(cfg, board, body: dict, *, approve, sendback, run_kb, gate_of) -> dict:
    card = board.get(str(body.get("id") or ""))
    mode = body.get("mode")
    doc_name = body.get("doc") or "plan"
    if mode not in MODES:
        raise SendError(f"a send is one of {', '.join(MODES)}")
    gate = gate_of(card)
    want = "plan" if doc_name == "plan" else "outcome"
    if gate != want:
        raise SendError(f"{card['id']} has no {want} gate open to answer (it is at {card['stage']})")
    events = board.events(card["id"])
    answer = receipt.receipt(cfg, card, events, want)
    if not receipt.answerable(card, answer, want):
        # c-537: a stale tab, or a second tap, never answers a gate twice
        raise SendError(f"{card['id']}'s {want} gate is answered already: {answer['said'][0].lower() + answer['said'][1:]}, "
                        f"{answer['now']}")
    doc = document(cfg, card, doc_name)
    state = planstate.state_of(events, doc_name)
    if mode == "sendback" and not planstate.has_words(state):
        # c-600: a send back is his reason; the pane's asks for one, and so does the page
        raise SendError(f"a send back needs your reason: add a note (or change an answer) on "
                        f"the {want}, then send it back; nothing was sent")
    text = planstate.compose(doc, state, mode, card["id"], doc_name)
    blocked = receipt.refused_block(card) if answer and answer["again"] and mode == "approve" else None
    if blocked:
        # Approve again after a refused landing: that refusal's block, and only it, is cleared
        run_kb(cfg, ["unblock", card["id"], "--expect", blocked])
    if mode == "approve":
        try:
            result = approve(cfg, board, {"verb": "approve", "id": card["id"], "gate": gate, "said": text})
        except Exception:
            if blocked:
                put_back(cfg, board, card["id"], blocked, run_kb)
            raise
    else:
        result = sendback(cfg, board, {"id": card["id"], "reason": text})
    mark = {"what": "sent", "doc": doc_name, "mode": mode, "decisions": planstate.decision_ids(doc)}
    run_kb(cfg, ["mark", card["id"], "--data=" + json.dumps(mark)])
    out = dict(result) if isinstance(result, dict) else {"result": result}
    out["composed"] = text
    return out


def put_back(cfg, board, card_id: str, blocked: str, run_kb) -> None:
    """Approve again failed after it cleared the refusal: put the refusal back, unless the
    approve took effect before the failure (a land relay is on the card, or it moved on),
    which a block would silently cancel. A put-back that fails never hides the approve's
    own error, which the caller raises."""
    try:
        card = board.get(card_id)
        took = card["stage"] != "review" or any(
            r.get("what") == "land" for r in (card.get("derived") or {}).get("relays") or [])
        if not took and not card.get("blocked_reason"):
            run_kb(cfg, ["block", card_id, blocked])
    except Exception:  # noqa: BLE001 - the approve's error is the one he needs to see
        pass
