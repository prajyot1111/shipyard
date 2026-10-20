"""The receipt a gate leaves once it is answered (c-537): who answered, when, and what is
happening now.

After Approve on the plan page nothing said what happened, and the buttons came back once
the command went through: an outcome approve leaves the card at review while it lands, so
the gate still read open. This module is the one place that decides whether a gate was
answered and what follows, read from the card's own events and state (one store: nothing
here is written). The plan page (`keel/planroute.py`) and the Inspector (`keel/deckstate.
detail`) carry what it says, and the page draws it (`app/ui.receipt.js`).

An ANSWER is the newest of these after the gate last opened (the newest `stage` event into
planning or review):

- the plan: an `approve` event for the plan gate, or the plan page's `sent` mark (a Send
  back leaves the card at planning, so the mark is its only record, and the house's Stop
  hook after it, the revised plan, opens the gate again);
- the outcome: a `land` relay (his queued tap, or Bosun's checked approval), an `approve`
  that is not the drain's own landing, the page's `sent` mark, or his move from review back
  to building (a Send back from the deck).

The gate is OPEN to another answer only while it is open on the board and nothing answered
it, or its landing was refused: that refusal is the one answer that offers Approve again.
"""

from __future__ import annotations

import json
import re

from keel import artifacts, terms

GATE_STAGE = {"plan": "planning", "outcome": "review"}
# Who answered, in the page's words.
BY = {"human": "you", "voice": "you, by voice", "bosun": "Bosun"}
SUITE_LOG = "merged-tests.log"      # merging.SUITE_LOG, not imported: merging is heavy
NOT_MERGED = "outcome not merged: "  # landing.NOT_MERGED, the block a refusal leaves
MERGED_INTO = re.compile(r"merged into (\S+)")
NOT_PUSHED = "locally, not pushed"   # how a landing's record ends (`merging.land_card`, c-665)
WHOLE_OUTPUT = re.compile(r";? the whole output is in \S+")


def opened_at(events: list[dict], gate: str) -> int:
    """The id of the event that last opened this gate: the newest stage move into its stage."""
    stage = GATE_STAGE[gate]
    return max((e["id"] for e in events
                if e["kind"] == "stage" and (e.get("data") or {}).get("to") == stage), default=0)


def answer_of(event: dict, gate: str) -> str | None:
    """`approve` or `sendback` when this event answers the gate, else None."""
    kind, data = event["kind"], event.get("data") or {}
    if kind == "mark" and data.get("what") == "sent" and (data.get("doc") or "plan") == gate:
        return data.get("mode") if data.get("mode") in ("approve", "sendback") else None
    if kind == "approve" and data.get("gate") == gate and event["actor"] != "drain":
        return "approve"
    if gate == "outcome" and kind == "relay" and data.get("what") == "land":
        return "approve"
    if (gate == "outcome" and kind == "stage" and data.get("from") == "review"
            and data.get("to") == "building" and event["actor"] in BY
            and str(event.get("text") or "").startswith(SENT_BACK)):
        return "sendback"                   # never the tap's merge-conflict move, which approved
    return None


SENT_BACK = "sent back"                     # the note `actions.act_sendback` moves the card with
TURN_ENDS = ("Stop", "SessionEnd")          # drain.TURN_END_HOOKS


def turn_ended(event: dict, session: str | None) -> bool:
    """The house's turn ended: a Stop or SessionEnd from the session the card carries now
    (or naming none), the drain's own rule (`drain.own_hook`); a superseded session's is not."""
    data = event.get("data") or {}
    return (event["kind"] == "hook" and data.get("hook") in TURN_ENDS
            and data.get("session_id") in (None, session))


def superseded_relays(events: list[dict]) -> set:
    """The relays a drain answered without acting on them: no answer of his stands on one."""
    return {(e.get("data") or {}).get("relay") for e in events
            if e["kind"] == "carried" and (e.get("data") or {}).get("outcome") == "superseded"}


def answered(events: list[dict], gate: str, session: str | None = None) -> dict | None:
    """The gate's newest answer since it last opened, or None. The approve event and the
    page's `sent` mark that follows it are one answer: the first of a run is kept.

    A plan Send back is answered only until the house ends the turn it was resumed with:
    it revises the plan IN PLACE (`prompts.sendback_plan`), which moves no stage, so its
    Stop hook is what opens the gate to him again."""
    since = opened_at(events, gate)
    dropped = superseded_relays(events)
    found = None
    for event in events:
        if (found and found["mode"] == "sendback" and gate == "plan" and turn_ended(event, session)
                and event["id"] > found["event"]):
            found = None
            continue
        if event["id"] <= since:
            continue
        mode = answer_of(event, gate)
        if mode is None or (event["kind"] == "relay" and event["id"] in dropped):
            continue
        if found and found["mode"] == mode and event["kind"] == "mark":
            continue                        # the mark that closes the round, not a new answer
        found = {"gate": gate, "mode": mode, "actor": event["actor"], "at": event["at"],
                 "event": event["id"], "kind": event["kind"]}
    return found


def said(found: dict) -> str:
    verb = "Approved" if found["mode"] == "approve" else "Sent back"
    return f"{verb} by {BY.get(found['actor'], found['actor'])}"


def first_line(text: str | None) -> str:
    """The first line, without the suite log's path (the receipt links the log instead)."""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return WHOLE_OUTPUT.sub("", line)


HELD = "held until the house's turn ends"


def resumed(card: dict, doing: str) -> str:
    """"house resumed, <doing>", or what is true instead: his tap still waiting on the board
    for a house the deck saw working (a pending `resume` relay marked `held`, c-604: the
    receipt said "house resumed" while it was held), or a card with no house session."""
    if not card.get("session_id"):
        return f"{doing}, with no house session to resume"
    relays = (card.get("derived") or {}).get("relays") or []
    if any(relay.get("what") == "resume" and relay.get("held") for relay in relays):
        return f"{HELD}, then {doing}"
    return f"house resumed, {doing}"


def plan_now(card: dict, found: dict) -> dict:
    stage, blocked = card["stage"], card.get("blocked_reason")
    if blocked:
        return {"now": "blocked: " + first_line(blocked), "tone": "warn"}
    if found["mode"] == "sendback":
        if stage == "planning":
            return {"now": resumed(card, "revising the plan"), "tone": "accent"}
        return {"now": f"at {stage}", "tone": None}
    if stage == "building":
        return {"now": resumed(card, "building"), "tone": "accent"}
    if stage == "review":
        return {"now": "built: the outcome waits for you", "tone": "accent", "link": "outcome"}
    return {"now": f"at {stage}", "tone": "good" if stage == "done" else None}


def target_of(cfg, card: dict, landing: dict) -> str | None:
    found = MERGED_INTO.search(str(landing.get("published") or ""))
    if found:
        return found.group(1)
    return cfg.integration_of(card.get("space"), card.get("repo")) if cfg is not None else None


def landed_now(cfg, card: dict, landing: dict) -> dict:
    target = target_of(cfg, card, landing)
    sha = str(landing.get("merge") or landing.get("sha") or "")[:7]
    words = "landed" + (f" on {target}" if target else "") + (f" at {sha}" if sha else "")
    integration = cfg.integration_of(card.get("space"), card.get("repo")) if cfg is not None else None
    if integration and target == integration:
        words += ", goes live with the next deploy"
    if str(landing.get("published") or "").endswith(NOT_PUSHED):
        words += ", not pushed"
    return {"now": words, "tone": "good"}


def log_link(cfg, card: dict, why: str) -> str | None:
    """The refused suite's whole output, as the deck serves a card's file, when the refusal
    names it (a refusal that ran no suite leaves an older run's log beside it) and it is here."""
    if cfg is None or SUITE_LOG not in why:
        return None
    path = cfg.cards_dir / card["id"] / SUITE_LOG
    if not path.is_file():
        return None
    url, _ = artifacts.target(cfg, path.parent, SUITE_LOG)
    return url


def outcome_now(cfg, card: dict, found: dict) -> dict:
    stage, derived = card["stage"], card.get("derived") or {}
    landing = (card.get("options") or {}).get("landing") or {}
    mine = landing.get("relay") == found["event"] if found["kind"] == "relay" else True
    if found["mode"] == "sendback":
        if stage == "building":
            return {"now": resumed(card, "revising the work"), "tone": "accent"}
        return {"now": f"at {stage}", "tone": None}
    if derived.get("landing"):
        if landing.get("state") == "testing" and mine:
            return {"now": f"landing, testing the merged tree on {landing.get('host') or 'its machine'}",
                    "tone": "accent"}
        to = next((r.get("to") for r in derived.get("relays") or [] if r.get("what") == "land"), None)
        return {"now": "landing, queued" + (f" for {to}" if to else ""), "tone": "accent"}
    if landing.get("state") == "refused" and mine:
        full = (landing.get("why") or "").strip()
        why = first_line(full)
        if stage == "building" and derived.get("bosun"):
            # c-647: the landing recorded Bosun's own sentence (`landing.bosun_why`), which
            # says the card waits on Bosun; no house is merging anything
            return {"now": f"refused: {why}", "tone": "warn"}
        if stage == "building":
            return {"now": f"refused: {why}; the house is merging it first", "tone": "warn"}
        return {"now": "refused: " + why, "tone": "crit", "log": log_link(cfg, card, full),
                "again": stage == "review"}
    if landing.get("state") == "landed" and mine and stage == "done":
        return landed_now(cfg, card, landing)
    if card.get("blocked_reason"):
        return {"now": "blocked: " + first_line(card["blocked_reason"]), "tone": "warn"}
    if stage == "done":
        return {"now": tap_landed(cfg, card, found) or "done", "tone": "good"}
    if stage == "shipping":
        return {"now": "shipping: its house answers the reviewers, and your Ship sends it; done when it merges", "tone": "accent"}
    return {"now": f"at {stage}", "tone": None}


def tap_landed(cfg, card: dict, found: dict) -> str | None:
    """The tap's own landing (the merge queue off): the approve event says what it published."""
    if found["kind"] != "approve":
        return None
    published = found.get("published") or ""
    if isinstance(published, str) and MERGED_INTO.search(published):
        return landed_now(cfg, card, {"published": published, "merge": published.split(" ")[0]})["now"]
    return published_line(published, terms.of(cfg, card.get("space")))


def published_line(published, t=None) -> str | None:
    """An adapter's answer as a sentence (c-601): a review round's publish answers a record
    (`{"posted": [...], "pr": 1, ...}`), and the receipt printed it as raw JSON. `t` is the
    card's space's terms (c-630)."""
    record = published
    if isinstance(published, str):
        try:
            record = json.loads(published)
        except ValueError:
            return published or None
    if not isinstance(record, dict):
        return str(record) if record else None
    parts = []
    if record.get("pr"):
        parts.append(terms.say(t, "{change} #") + str(record["pr"]))
    if record.get("pushed"):
        parts.append(f"pushed {str(record['pushed'])[:10]}")
    if isinstance(record.get("posted"), list):
        count = len(record["posted"])
        parts.append(f"{count} {'reply' if count == 1 else 'replies'} posted")
    return "published: " + ", ".join(parts) if parts else "published"


def receipt(cfg, card: dict, events: list[dict], doc: str | None) -> dict | None:
    """What the page shows once the gate is answered, or None while nobody has answered it.
    `doc` is the plan page's document; None (the Inspector) takes the newer of the two."""
    gates = [doc] if doc else ["plan", "outcome"]
    found = [a for a in (answered(events, g, card.get("session_id")) for g in gates) if a]
    if not found:
        return None
    newest = max(found, key=lambda a: a["event"])
    newest["published"] = published_of(events, newest)
    now = plan_now(card, newest) if newest["gate"] == "plan" else outcome_now(cfg, card, newest)
    later = answered(events, "outcome", card.get("session_id")) if newest["gate"] == "plan" and card["stage"] != "building" else None
    if later and newest["mode"] == "approve":
        # the plan page of a card whose outcome was answered since: what follows is that
        later["published"] = published_of(events, later)
        now = dict(outcome_now(cfg, card, later), link="outcome")
    return {"gate": newest["gate"], "mode": newest["mode"], "actor": newest["actor"],
           "at": newest["at"], "said": said(newest), "now": now["now"], "tone": now.get("tone"),
           "log": now.get("log"), "link": now.get("link"), "again": bool(now.get("again"))}


def published_of(events: list[dict], found: dict) -> str | None:
    """What an approve event says it published (the tap's own landing)."""
    if found["kind"] != "approve":
        return None
    event = next((e for e in events if e["id"] == found["event"]), {})
    return (event.get("data") or {}).get("published")


def gate_of(card: dict) -> str | None:
    derived = card.get("derived") or {}
    return "plan" if derived.get("plan_gate") else ("outcome" if derived.get("outcome_gate") else None)


def answerable(card: dict, found: dict | None, doc: str) -> bool:
    """May this document's gate take an answer now: open on the board, and either nobody has
    answered it since it opened or its landing was refused (Approve again)."""
    if gate_of(card) != doc:
        return False
    return found is None or found["gate"] != doc or found["again"]


def refused_block(card: dict) -> str | None:
    """The block a refused landing left, which Approve again clears (and only that one)."""
    reason = card.get("blocked_reason") or ""
    return reason if reason.startswith(NOT_MERGED) else None
