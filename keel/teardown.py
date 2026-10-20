"""A card's own containers torn down when it leaves building, as a drain upkeep step (c-532).

A house brings up its own containers to prove its change (a test stack, previews), and
they belong to the building spell that started them. Once the card leaves building (the
house staged it to review, he approved it to shipping or done, or it was archived) they
are only holding the machine's container memory, which the houses share. c-272 sat at
review with its stack and a preview still up.

So, on the machine that holds the house, each pass finds a card whose newest move INTO
building (a stage move, or his plan approval, which is recorded as an `approve` event) has
not been answered yet, asks the adapter's `ship <id> down` to stop and
remove that card's OWN containers (what counts as its own is the adapter's, and its
worktree is kept), records the answered move's event id in `options.torn_down`, and notes
on the card what went. A new building spell (a send back, a review round) is torn down
again when it ends. A card waits for a later pass while its house is working, while he
holds it (a Drop in or a voice hold: he may be looking at its preview), and while another
card still at building records the same worktree (a branch two cards share: those
containers are that card's too).

A card at SHIPPING (c-600) keeps its house, which answers each review batch in a turn and
may bring its stack up again to prove a fix. Each such turn is a spell too, answered by the
house's Stop: the newest Stop hook after the card moved to shipping is the spell's id, so
the stack goes down once the turn ends, and again after the next one (c-600 review). A hook
does not touch the card's `updated_at`, so a shipping card is never cached in `CHECKED`.

At most `PER_PASS` cards a pass, and the whole step within `BUDGET_SECONDS`: each card's
adapter run is given what is left of the budget (at most `DOWN_SECONDS`), and none starts
with under `MIN_SECONDS` left. The first pass after this shipped finds every old card due
once, and a pass must stay short. `CHECKED` remembers, for
this process only, the cards found not due at a given `updated_at`, so a quiet card costs
no event read on every pass; a restarted drain simply looks again (a schedule, not a
record, as in `keel/shipping.py`).
"""

import json
import subprocess
import time

from keel import adapters, views
from keel.config import Config

SHIP_VERB = "ship"
TEARDOWN_OPTION = "torn_down"
PER_PASS = 4
BUDGET_SECONDS = 120
DOWN_SECONDS = 120
MIN_SECONDS = 30
# card id -> the `updated_at` at which it was last found not due, in this process.
CHECKED: dict[str, str] = {}


def left_building(card: dict) -> bool:
    return card.get("stage") != "building" or bool(card["derived"]["archived"])


def candidate(cfg: Config, card: dict, served: set[str]) -> bool:
    """A card of a space this pass serves whose adapter can tear down, whose house is on
    this machine, that has left building and had a worktree cut."""
    space = cfg.spaces.get(card.get("space"))
    if space is None or card["space"] not in served or not left_building(card):
        return False
    options = card.get("options") or {}
    if not (options.get("worktree") or options.get("worktrees")):
        return False
    return adapters.has_verb(space, SHIP_VERB)


def paths_of(card: dict) -> set[str]:
    options = card.get("options") or {}
    recorded = options.get("worktrees")
    found = set(recorded.values()) if isinstance(recorded, dict) else set()
    return {str(p) for p in found | {options.get("worktree")} if p}


def building_paths(cards: list[dict]) -> set[str]:
    """The worktrees of every card still building: nothing in them is torn down."""
    return {p for card in cards if not left_building(card) for p in paths_of(card)}


def waits(card: dict, rows: list[dict], busy_paths: set[str]) -> bool:
    """Its house is working, he holds it, or a card still building shares its worktree."""
    options = card.get("options") or {}
    if views.voice_hold(options) or views.dropin_hold(options):
        return True
    if paths_of(card) & busy_paths:
        return True
    return any(row.get("name") == card["id"] and row.get("status") == "busy" for row in rows)


def spell(board, card_id: str) -> int | None:
    """The id of the card's newest spell, or None when it never built: its newest move into
    building (any event kind that moves it: a plan approval is an `approve` event, not a
    `stage` one), or, later than that, a Stop of its house after it moved to shipping."""
    stop = None
    for event in reversed(board.events(card_id)):
        data = event.get("data") or {}
        if event.get("kind") == "hook" and data.get("hook") == "Stop" and stop is None:
            stop = event.get("id")
        if data.get("to") == "shipping" and data.get("from") != "shipping" and stop is not None:
            return stop
        if data.get("to") == "building" and data.get("from") != "building":
            return event.get("id")
    return None


def shipping_turns(card: dict) -> bool:
    """A card whose house answers review in turns (c-600): not cached, see the module."""
    return card.get("stage") == "shipping"


def due(board, card: dict) -> int | None:
    """The building spell to answer, or None when the newest one already was."""
    if CHECKED.get(card["id"]) == card.get("updated_at"):
        return None
    started = spell(board, card["id"])
    if started is None or (card.get("options") or {}).get(TEARDOWN_OPTION) == started:
        if not shipping_turns(card):
            CHECKED[card["id"]] = card.get("updated_at")
        return None
    return started


def said(out: dict) -> str | None:
    """One note from the adapter's answer, or None when nothing went and nothing failed."""
    parts = []
    if out.get("down"):
        parts.append(f"{out.get('why') or 'left building'}, so its own containers were torn down: "
                     + ", ".join(out["down"]) + " (the worktree is kept)")
    if out.get("failed"):
        parts.append("the teardown could not finish: " + "; ".join(out["failed"]))
    return "; ".join(parts) or None


def tear_down(cfg: Config, board, card: dict, started: int,
              timeout: float = DOWN_SECONDS) -> dict:
    """The adapter's `ship <id> down`, the spell recorded as answered whatever it said (a
    failure is noted once, not retried every pass), and one note when anything happened."""
    space = cfg.spaces[card["space"]]
    try:
        out = json.loads(adapters.run(space, SHIP_VERB, card["id"], "down",
                                      timeout=timeout) or "{}")
    except (adapters.AdapterError, ValueError, OSError, subprocess.SubprocessError) as error:
        out = {"failed": [str(error).splitlines()[0] if str(error) else "the adapter failed"]}
    board.set_fields(card["id"], {"options": {TEARDOWN_OPTION: started}}, "drain")
    out = out if isinstance(out, dict) else {}
    if card.get("stage") == "shipping" and out.get("down"):
        out["why"] = "its house's review turn ended"
    note = said(out)
    if note:
        board.note(card["id"], note, "drain")
    return out


def upkeep(cfg: Config, board, served: set[str], rows: list[dict],
           clock=time.monotonic) -> list[str]:
    """One pass: the ids of the cards that had something torn down (a card asked that had
    nothing up, or that failed, is not one; its note says so). The caller keeps a failure
    to the step."""
    done, asked, began = [], 0, clock()
    cards = board.list_cards()
    busy_paths = building_paths(cards)
    for card in cards:
        left = BUDGET_SECONDS - (clock() - began)
        if asked >= PER_PASS or left < MIN_SECONDS:
            break
        if not candidate(cfg, card, served) or waits(card, rows, busy_paths):
            continue
        started = due(board, card)
        if started is None:
            continue
        asked += 1
        if tear_down(cfg, board, card, started, min(DOWN_SECONDS, left)).get("down"):
            done.append(card["id"])
    return done
