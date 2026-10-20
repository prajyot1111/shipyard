"""The one-time carry of work cards from the review-round model to the living house (c-600
review), which `bin/keel-shipping-upgrade` runs.

Before c-600 a review round sent a shipping card back to building with the batch as
`options.shipping.batch`, a fresh session wrote replies into the outcome record, and his
Approve at review pushed and posted them. Now the card stays at shipping, the batch is
`told` to the same house, the house records one `kb verdict` per item, and his Ship
pushes and posts. For each work card this says what it would do (a dry run by default):

- **At shipping** with an old answered batch: the batch is copied into `told` with its
  round, and each of its handles is recorded as posted (`LEGACY`), so nothing already said
  on the pull request is said again. The house's settings file is rewritten here (the
  fence: the shipping deny list, the guard hook with the card's id) when this machine holds
  it; a live session certainly reads it at its next resume or tell.
- **Mid-round** (at review or building with a round's batch): the batch goes back to
  `pending`, due at once, so that after his Approve (a plain publish now, which moves the
  card to shipping) it is told to the house under the new rules and judged with verdicts.
  The round's commits are pushed by his Ship, never by that Approve.
- **Declined at review** (the old model's way): said, left for him (Archive, or Approve,
  which publishes afresh as it always did).
- The old `ship_now` option and `rotated` flag are dropped.

It never stops, starts or resumes a session. `refusal` is what Approve at review says for a
card not carried yet.
"""

from __future__ import annotations

import copy

LEGACY = "legacy"
OLD_OPTION = "ship_now"
MID_ROUND = ("review", "building")


def shipping_of(card: dict) -> dict:
    return dict((card.get("options") or {}).get("shipping") or {})


def old_round(card: dict) -> bool:
    """A card still carrying the old model's round batch, at shipping or mid-round."""
    shipped = shipping_of(card)
    return isinstance(shipped.get("batch"), list) and card.get("stage") in ("shipping", *MID_ROUND)


def refusal(card: dict) -> str | None:
    """Why his Approve at review cannot run on this card as it stands (an old round not yet
    carried); None when it can."""
    shipped = shipping_of(card)
    if card.get("stage") != "review" or not shipped:
        return None
    if old_round(card):
        return (f"{card['id']} is in a review round from before the living-house deploy (round "
                f"{shipped.get('round')}): run `keel-shipping-upgrade --run` first. Then Approve "
                f"moves it to shipping, its house is told the round's items again, and your "
                f"Ship pushes its commits and posts the replies you keep; nothing was published")
    return None


def carried(card: dict) -> dict:
    """The card's shipping record under the new model."""
    new = copy.deepcopy(shipping_of(card))
    batch = [dict(item) for item in new.pop("batch", None) or [] if isinstance(item, dict)]
    new.pop("rotated", None)
    number = int(new.get("round") or 0)
    at = new.get("round_at") or new.get("since")
    if card.get("stage") == "shipping":
        handles = {item.get("handle") for item in batch}
        told = [item for item in new.get("told") or [] if item.get("handle") not in handles]
        new["told"] = told + [dict(item, batch=number, told_at=at) for item in batch]
        posted = dict(new.get("posted") or {})
        posted.update({str(item["handle"]): LEGACY for item in batch if item.get("handle")})
        new["posted"] = posted
    else:
        handles = {item.get("handle") for item in batch}
        pending = [item for item in new.get("pending") or [] if item.get("handle") not in handles]
        new["pending"] = batch + pending
        if batch:
            new["first_at"] = new["last_at"] = at     # long quiet already: due at once
    return new


def plan(card: dict, settings_current: bool = False) -> list[str]:
    """What the upgrade would do to this card, one line each; [] when nothing.
    `settings_current`: this machine read the house's settings file and it already says what
    a rewrite would (c-604), so no rewrite is proposed; unknown (a deck's dry run) is False."""
    shipped = shipping_of(card)
    options = card.get("options") or {}
    steps = []
    if old_round(card):
        size = len(shipped.get("batch") or [])
        if card.get("stage") == "shipping":
            steps.append(f"copy round {shipped.get('round')}'s {size} item(s) into told, each "
                         f"recorded as posted, so nothing is said twice")
        else:
            steps.append(f"mid-round at {card['stage']}: round {shipped.get('round')}'s {size} "
                         f"item(s) back to pending, told to the house after the user's Approve; the user's "
                         f"Ship pushes the round's commits")
    elif shipped.get("rotated"):
        steps.append("drop the old rotated flag")
    if OLD_OPTION in options:
        steps.append(f"drop the old {OLD_OPTION} option")
    if card.get("stage") == "shipping" and card.get("session_id") and not settings_current:
        steps.append("rewrite the house's settings (the shipping fence) where this machine holds "
                     "it; a live house reads it at its next tell or resume")
    if card.get("stage") == "review" and shipped.get("state") == "declined":
        steps.append("declined at review (the old way): nothing to carry; Archive is the user's")
    return steps


def fields(card: dict) -> dict | None:
    """The options this upgrade writes for the card, or None when it writes nothing."""
    options = card.get("options") or {}
    shipped = shipping_of(card)
    out = {}
    if old_round(card) or shipped.get("rotated"):
        out["shipping"] = carried(card)
    if OLD_OPTION in options:
        out[OLD_OPTION] = None
    return {"options": out} if out else None


def work_cards(cards: list[dict], spaces: set[str] | None = None) -> list[dict]:
    """The cards the upgrade looks at: a shipping record, or at shipping, not archived."""
    out = []
    for card in cards:
        if spaces is not None and card.get("space") not in spaces:
            continue
        if (card.get("derived") or {}).get("archived"):
            continue
        if card.get("stage") == "shipping" or shipping_of(card) or OLD_OPTION in (card.get("options") or {}):
            out.append(card)
    return out


# ----- the command -----

NOTE = "carried to the living-house review (c-600): {steps}"


def cards_from_deck(url: str, fetch=None) -> list[dict]:
    """The live deck's cards, read-only (a GET of its state), for a dry run's plan."""
    import json                     # noqa: PLC0415
    import urllib.request           # noqa: PLC0415
    fetch = fetch or (lambda u: urllib.request.urlopen(u, timeout=30).read())
    state = json.loads(fetch(url.rstrip("/") + "/api/state?scope=deck"))
    return list(state.get("cards") or [])


def report(cards: list[dict], current=None) -> list[str]:
    """The plan for every work card; `current(card)` says whether its house's settings are
    already current (None: nobody can tell from here)."""
    lines = []
    for card in work_cards(cards):
        steps = plan(card, bool(current and current(card)))
        if steps:
            lines.append(f"{card['id']} ({card.get('stage')}):")
            lines += [f"  - {step}" for step in steps]
    return lines or ["nothing to carry: no work card has an old round, flag or option"]


def apply(cfg, board, card: dict) -> list[str]:
    """Write what `plan` says for one card, and rewrite its house's settings when this
    machine holds that house. Never a session call."""
    from keel import house, views  # noqa: PLC0415 - the deck's dry run needs neither
    steps = plan(card, held_current(cfg, card))
    wanted = fields(card)
    if wanted:
        board.set_fields(card["id"], wanted, "human")
    if (card.get("stage") == "shipping" and card.get("session_id")
            and not house.settings_current(cfg, board.get(card["id"]))):
        house.settings_for(cfg, board.get(card["id"]))
    if steps:
        # one pass over many cards: never his own action on this one (the backlog clock, c-673)
        board.note(card["id"], NOTE.format(steps="; ".join(steps)), "human", data=views.BULK_DATA)
    return steps


def held_current(cfg, card: dict) -> bool:
    """The card's settings file is here and already current; False when it is not, or is
    not on this machine (then the rewrite stays in the plan, said as where it is held)."""
    from keel import house         # noqa: PLC0415
    return bool(card.get("session_id")) and house.settings_current(cfg, card)


def main(argv: list[str] | None = None) -> int:
    import argparse                 # noqa: PLC0415
    parser = argparse.ArgumentParser(prog="keel-shipping-upgrade",
                                     description="carry work cards to the living-house review (c-600)")
    parser.add_argument("--run", action="store_true", help="apply it (the default only prints)")
    parser.add_argument("--deck", metavar="url", help="print the plan from a live deck's state (read-only)")
    args = parser.parse_args(argv)
    if args.deck:
        if args.run:
            parser.error("--deck only reads; run --run on the machine that holds the board")
        print("\n".join(report(cards_from_deck(args.deck))))
        return 0
    from keel import config as config_module    # noqa: PLC0415
    from keel.board import open_board
    cfg = config_module.load()
    board = open_board(cfg)
    try:
        cards = board.list_cards()
        print("\n".join(report(cards, lambda card: held_current(cfg, card))))
        if not args.run:
            print("(a dry run: nothing was written; --run applies it)")
            return 0
        for card in work_cards(cards):
            apply(cfg, board, card)
        print("applied")
        return 0
    finally:
        board.close()
