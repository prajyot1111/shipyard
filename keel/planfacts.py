"""What a card row and Attention say about a plan or an outcome in the format (P4-5).

The plan page counts his round from the parse and the lint (`keel/planroute.py`); the row
used to say only "gate open". This is the same parse and the same lint, reduced to the few
numbers a row can carry, in two halves because they live in two places:

- **The document's half** (`doc_facts`): whether each of the card's two documents is in the
  format at all, its decisions and open questions, the recommendation of each, and whether
  the contract holds. It is read with the card's links (`deckstate.links_for`), cached per
  file stamp (path, mtime, size), so a state build reads a plan once per change, not once
  per poll.
- **The round's half** (`row`): his notes this round, the decisions he changed, and his
  Asks, open or answered, read off the card's events.

The lint here leaves out the `path:line` check (C7): it runs `git` once per path, which a
state build must not, and `kb stage` already refused a plan whose refs did not resolve. The
page runs it whole. Board ids are checked against the board store.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from keel import artifacts, planformat, plangate, planlint, planstate
from keel.review import gate as review_gate

CACHE_MAX = 256
_cache: OrderedDict = OrderedDict()
GATE_DOC = {"plan": "plan", "outcome": "outcome"}


def stamp(path: Path) -> tuple | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def is_format(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4).startswith(b"---")
    except OSError:
        return False


def paths_of(cfg, card: dict) -> dict:
    """The card's two documents on this machine: the plan when it is a markdown file, and
    `context.md`. A path that is not here is left out."""
    out = {}
    ref = str(card.get("plan_ref") or "")
    if ref and not ref.startswith("http"):
        plan = artifacts.local_path(ref, cfg.root)
        if artifacts.kind(plan) == "markdown":
            out["plan"] = plan
    out["outcome"] = cfg.card_dir(card["id"]) / "context.md"
    return out


def doc_facts(cfg, card: dict) -> dict:
    """`{"plan": facts or None, "outcome": facts or None}` for the documents on this
    machine; None for a document that is missing or not in the format."""
    board_of = plangate.board_resolver(cfg)
    out = {}
    for doc, path in paths_of(cfg, card).items():
        out[doc] = file_facts(path, bool(card.get("repo")), board_of, card.get("id"),
                              review_gate.started_with_pipeline(card), legacy=doc == "outcome",
                              research=planlint.writes_research(card), review=planlint.review_card(card),
                              role=planlint.RECORD if doc == "outcome" else planlint.PLAN)
    return out


def file_facts(path: Path, repo_card: bool, board_of, card_id: str | None,
               ships: bool = False, legacy: bool = False, research: bool = False, review: bool = False,
               role: str | None = None) -> dict | None:
    """`legacy`: an outcome is counted as the page reads it, so a review already written in
    the old findings shape is not called broken on its row (lane FC)."""
    key = stamp(path)
    if key is None or not is_format(path):
        return None
    key = (*key, repo_card, board_of is not None, ships, legacy, research, review, role)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    doc = planformat.parse(path.read_text(errors="replace"), path.name)
    # c-719 r1.F1: the record is held to the card's contract, as the page and the gate hold it
    kind = "review" if review else "research" if research else None      # a review card stays one
    mismatch = planlint.follow_card(doc, {"id": card_id, "repo": None if research else "-",
                                          "options": {"kind": kind} if kind else {}}, path.name, role)
    result = planlint.with_findings(planlint.lint(doc, repo_card=repo_card, board_of=board_of, card_id=card_id,
                                                  ships=ships, legacy=legacy, written=legacy), mismatch)
    facts = summarise(doc, result)
    _cache[key] = facts
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return facts


def summarise(doc: dict, result: dict) -> dict:
    """The document's half: what it asks, what it recommends, whether it holds."""
    blocks = list(planformat.all_blocks(doc["blocks"]))
    recs = {b["id"]: b.get("rec") for b in blocks if b["type"] == "decision"}
    rows = {b["id"]: {r["id"]: r.get("rec") for r in b.get("rows", [])}
            for b in blocks if b["type"] == "batch"}
    rows.update({b["id"]: {b["id"]: b.get("rec")} for b in blocks if b["type"] == "finding"})
    errors = sum(1 for f in result["findings"] if f["level"] == "error")
    return {"kind": doc["kind"], "decisions": len(recs) + sum(len(r) for r in rows.values()),
            "questions": sum(len(b.get("items", [])) for b in blocks if b["type"] == "questions"),
            "recs": recs, "rows": rows, "ok": result["ok"], "breaks": errors}


def gate_doc(card: dict) -> str | None:
    """The document his open gate is about: the plan at the plan gate, the outcome at the
    outcome gate, none otherwise."""
    derived = card.get("derived") or {}
    if derived.get("plan_gate"):
        return "plan"
    if derived.get("outcome_gate"):
        return "outcome"
    return None


def row(docs: dict | None, card: dict, events: list[dict] | None) -> dict | None:
    """What the row says: the gate's document in the format, with his round counted from
    the card's events. None when the gate is closed or its document is not the format."""
    doc = gate_doc(card)
    facts = (docs or {}).get(doc) if doc else None
    if not facts:
        return None
    state = planstate.state_of(events or [], doc)
    changed = sum(1 for block, picked in state["answers"].items()
                  if picked.get("other") or picked.get("option") not in (None, facts["recs"].get(block)))
    changed += sum(1 for block, picks in state["rows"].items()
                   for row_id, choice in picks.items()
                   if choice not in (None, facts["rows"].get(block, {}).get(row_id)))
    asks = state["asks"]
    return {"doc": doc, "decisions": facts["decisions"], "questions": facts["questions"],
            "changed": changed, "notes": len(state["comments"]),
            "asks_open": sum(1 for a in asks if a["reply"] is None),
            "replies": sum(1 for a in asks if a["reply"] is not None),
            "ok": facts["ok"], "breaks": facts["breaks"]}


def formats(docs: dict | None) -> dict:
    """Which of the two documents is in the format, for the links the deck opens."""
    return {doc: bool((docs or {}).get(doc)) for doc in ("plan", "outcome")}
