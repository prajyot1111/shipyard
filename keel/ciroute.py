"""A card's CI page (c-642, docs/atlas/66-ci.md): `/ci/<id>` and its data, `/api/ci/<id>`.

The page is served by the plan page's shell (`app/plan.html`, `PLAN_PAGE` takes `ci`), so
plan, outcome and CI switch to each other from one header. Its data is the space's pack
answering `ci <id>` (the `ci` capability): the card's pull requests' checks and the CI
server's builds that carry its work. It is read when the page opens and on Refresh, never
kept: an external read on his look, so nothing has to agree with it. A pack reads the code
host and the CI server, not the house's worktree, so a card whose house is on the other
machine is read here the same way.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from keel import adapters, readiness, terms

CI_API = re.compile(r"^/api/ci/(c-\d+)$")
CAPABILITY = "ci"
SECONDS = 90                 # the pack reads two services, a few calls each


def offered(cfg, card: dict) -> bool:
    """A card has a CI page when it has a repo and its space's `ci` row is ready: the row the
    pane's CI button reads, so the header's link and the button agree (an adapter that
    predates packs declares nothing, so it has neither). The page itself still runs on a
    declared capability whose check fails, and says the verb's own words (`payload`)."""
    space = cfg.spaces.get(card.get("space") or "")
    if not card.get("repo") or space is None:
        return False
    return bool(readiness.capability_rows(cfg, space).get(CAPABILITY, {}).get("ready"))


def docs_of(cfg, card: dict) -> list[str]:
    """The pages the CI and comments pages' headers switch to: the ones the plan page lists
    (the plan and outcome that exist, read where the house is, then CI and comments)."""
    from keel import planroute     # noqa: PLC0415 - the plan route imports this module
    try:
        docs = list(planroute.read(cfg, card, "plan")["docs"])
    except Exception:  # noqa: BLE001 - a plan that cannot be read leaves the switch to CI alone
        docs = []
    return planroute.in_order(docs + planroute.more_pages(cfg, card))


def payload(cfg, card: dict) -> tuple[int, dict]:
    card_out = {key: card.get(key) for key in ("id", "title", "space", "stage", "repo")}
    card_out["terms"] = terms.public(terms.of(cfg, card.get("space")))
    from keel import planroute     # noqa: PLC0415 - the plan route imports this module
    head = {"card": card_out, "moves": planroute.moves_of(cfg, card),
            "docs": docs_of(cfg, card), "at": datetime.now().astimezone().isoformat(timespec="seconds")}
    space = cfg.spaces.get(card.get("space") or "")
    why = None if space is None else readiness.refusal(cfg, space, CAPABILITY)
    if space is None or why or not card.get("repo"):
        said = why or (f"{card['id']} has no repo, so nothing of it is built" if space else
                       f"{card['id']}'s space is not configured here")
        return 200, dict(head, ci=None, why=said)
    try:
        said = adapters.run(space, "ci", card["id"], timeout=SECONDS)
        found = json.loads(said or "null")
    except adapters.AdapterError as error:
        return 200, dict(head, ci=None, why=f"the CI read failed: {error}")
    except ValueError:
        return 200, dict(head, ci=None, why="the pack's ci answered something that is not JSON")
    return 200, dict(head, ci=found, why=None)


class CiRoute:
    """Mixed into the deck's request handler, as the plan route is."""

    def get_ci(self, card_id: str) -> None:
        board = self.deck.board_factory()
        try:
            card = board.get(card_id)
        except Exception as error:      # noqa: BLE001 - an unknown card is a 404 with its reason
            return self.reply_json(404, {"error": str(error)})
        finally:
            board.close()
        status, body = payload(self.cfg, card)
        self.reply_json(status, body)
