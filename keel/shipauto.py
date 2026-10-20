"""Automatic handling at shipping, one switch per kind of review (c-655).

His word (2026-10-05): what the watcher finds on a shipping card's pull request is two
kinds of work, and each goes to the card's house by itself only where he said so:

    comments   a reviewer's comment, and a submitted review asking for changes
    checks     a check that failed on the head

Each is a space's setting (`[spaces.<name>] ship_auto_comments`, `ship_auto_checks`, both
OFF by default, on the Settings page) and a card's own option of the same name, which wins
(`kb set <id> options.ship_auto_comments=true`, or the toggle on the shipping card; null
hands the card back to its space's). Only he sets a card's (`board.HUMAN_ONLY_OPTIONS`): a
house that could would be deciding what wakes it.

OFF MEANS COLLECTED, NOT TOLD. The watcher looks and folds as always (`shipwatch.fold`), so
a merge, a decline, the chip's facts and every comment's whole text are what they were.
Then `settle` puts each waiting item where its kind says: `pending` (the batch, told on
its timers) while its kind is on, `untold` (`shipwatch.UNTOLD`) while it is off. An untold
item is never told and never wakes or resumes a house, and it is never lost: it is not
baselined away, it survives a whole-record write, and his hand-over offers it
(`shipreoffer.fill`). Turned on later, the next look puts the untold items of that kind
back in the batch with their own times, so they go on that pass (`releasable` makes the
look come at the waiting cadence). Turned off with items in the batch, they go back to
`untold` at once, with no look. What he handed over himself is never parked (`handed`): a
filled re-offer goes whatever the switches say. Every successful look holds `untold` to the
code host first (`reconcile`): a comment deleted or resolved, a review withdrawn and a
check passing again stop waiting, with one note, so nothing stale is freed or counted.

The deck says all of it in words (`handover`, `chosen`; `app/ui.shipping.js`): what waits,
whether each kind is on, and the one button that hands the waiting review to the house,
which is `Board.reoffer` and works with the switches on or off.
"""

from __future__ import annotations

import copy

from keel import shipreoffer, shipreplies, shipwatch

COMMENTS, CHECKS = "comments", "checks"
# The space's setting and the card's option share one name per kind.
KEYS = {COMMENTS: "ship_auto_comments", CHECKS: "ship_auto_checks"}
# Which switch an item answers to; an item of no kind here (a `rebase`, or `his`, his own
# send-back at shipping, c-663) is his own ask, told whatever the switches say.
ITEM_KINDS = {"comment": COMMENTS, "review": COMMENTS, "ci": CHECKS}
UNTOLD = shipwatch.UNTOLD
# The events `handover` reads of a batch's turn (`shipreoffer.batch_turn`), after its mark.
TURN_KINDS = ("resume", "session", "hook", "set")


# ----- the two switches -----

def of_space(space) -> dict:
    """A space's own two values (`keel/config.py`'s `Space`); both off for no space."""
    return {kind: bool(getattr(space, key, False)) for kind, key in KEYS.items()}


def chosen(space_values: dict | None, options: dict | None) -> dict:
    """`{kind: {on, by}}` for one card: its own option where it is a bool (`by: card`),
    else its space's (`by: space`)."""
    options, out = options or {}, {}
    for kind, key in KEYS.items():
        own = options.get(key)
        mine = isinstance(own, bool)
        out[kind] = {"on": own if mine else bool((space_values or {}).get(kind)),
                     "by": "card" if mine else "space"}
    return out


def for_card(cfg, card: dict) -> dict:
    """`{comments, checks}` as bools: what the drain tells this card's house by itself."""
    picked = chosen(of_space(cfg.spaces.get(card.get("space"))), card.get("options"))
    return {kind: picked[kind]["on"] for kind in KEYS}


def option_problem(options: dict | None) -> str | None:
    """Why a set of options may not be written: a switch that is neither a bool nor null."""
    for key in KEYS.values():
        if key in (options or {}) and options[key] is not None and not isinstance(options[key], bool):
            return f"options.{key} is true, false, or null for the space's own, not {options[key]!r}"
    return None


# ----- where each waiting item waits -----

def automatic(item: dict, auto: dict) -> bool:
    kind = ITEM_KINDS.get(str(item.get("kind")))
    return kind is None or bool(auto.get(kind))


def handles(items: list[dict]) -> set[str]:
    return {str(item.get("handle")) for item in items}


def handed(shipped: dict) -> set[str]:
    """The handles of a hand-over the drain filled and has not told yet: his own ask, so
    they stay in the batch whatever the switches say."""
    mark = shipped.get(shipreoffer.RECORD_KEY) or {}
    return set() if not mark.get("filled_at") or mark.get("batch") else set(mark.get("items") or [])


def releasable(shipped: dict, auto: dict) -> bool:
    """Does an untold item's kind say tell it now (its switch was turned on)?"""
    return any(automatic(item, auto) for item in shipped.get(UNTOLD) or [])


def as_waiting(shipped: dict, auto: dict) -> dict:
    """The record as the cadence should read it (`shipwatch.poll_due`): with something to
    release, as a card with items waiting, so the look that releases them comes soon."""
    return dict(shipped, pending=[{}]) if releasable(shipped, auto) and not shipped.get("pending") else shipped


def live_reviews(sight: dict) -> dict:
    """What a look shows that can wait: `{handle: author}`, the author for a review asking
    for changes and None for a comment or a failed check, by the watcher's own handles."""
    live = {}
    for part, _primary, prefix in shipwatch.labelled_parts(sight):
        live.update({f"{prefix}c{found['id']}": None for found in part.get("comments") or []})
        live.update({f"{prefix}review-{shipwatch.slug(review['author'])}": review["author"]
                     for review in part.get("reviews") or [] if review.get("state") == "changes_requested"})
        if (part.get("ci") or {}).get("state") == "failed":
            live[f"{prefix}ci"] = None
    return live


def reconcile(shipped: dict, sight: dict) -> dict:
    """The record with `untold` held to a successful look (c-655 review): a comment no longer
    in the sight (deleted, or its thread resolved), a review that no longer asks for changes
    and a check that no longer fails are dropped, and a review that still asks carries the
    author the sight names, so what a kind turned on frees is never a stale item's word.
    It also keeps which comments and reviews asking for changes the look showed
    (`shipwatch.ON_HOST`), which is what the count and the ask hold "seen, never told" to.
    The same object when nothing changed."""
    untold, live = shipped.get(UNTOLD) or [], live_reviews(sight)
    kept = [dict(item, author=live[str(item.get("handle"))]) if live.get(str(item.get("handle"))) else item
            for item in untold if str(item.get("handle")) in live]
    host = sorted(handle for handle in live if handle != "ci" and not handle.endswith(".ci"))
    if kept == untold and shipped.get(shipwatch.ON_HOST) == host:
        return shipped
    new = {key: value for key, value in shipped.items() if key != UNTOLD}
    new[shipwatch.ON_HOST] = host
    return dict(new, **{UNTOLD: kept}) if kept else new


def gone(before: dict, after: dict) -> list[str]:
    """The handles that waited untold before a look and wait nowhere after it."""
    left = handles(after.get(UNTOLD) or []) | handles(after.get("pending") or [])
    return [str(item.get("handle")) for item in before.get(UNTOLD) or [] if str(item.get("handle")) not in left]


GONE_NOTE = ("no longer waiting for a hand-over: {handles} (gone from the {change}, withdrawn, or "
             "passing again)")


def settle(shipped: dict, auto: dict, release: bool = True) -> dict:
    """The record with every waiting item where its kind's switch says: off, out of the
    batch into `untold`; on, back into the batch (`release`: only on a fresh look, which has
    just taken back a check that passed meanwhile). The same object when nothing moves."""
    pending, untold = list(shipped.get("pending") or []), list(shipped.get(UNTOLD) or [])
    mine = handed(shipped)
    park = [item for item in pending if not automatic(item, auto) and str(item.get("handle")) not in mine]
    free = [item for item in untold if automatic(item, auto)] if release else []
    if not park and not free:
        return shipped
    new = copy.deepcopy(shipped)
    gone, back = handles(park), handles(free)
    stay = [item for item in pending if str(item.get("handle")) not in gone]
    # a newer one under the same handle (an edit seen on this look) is the one that goes
    new["pending"] = stay + [item for item in free if str(item.get("handle")) not in handles(stay)]
    rest = [item for item in untold if str(item.get("handle")) not in gone | back] + park
    new.pop(UNTOLD, None)
    if rest:
        new[UNTOLD] = rest
    retime(new, park, free)
    if isinstance(new.get("facts"), dict):
        new["facts"]["waiting"] = len(new["pending"])
    return new


def stamps(items: list[dict], kind: str) -> list:
    found = [shipwatch.parse(item.get("at")) for item in items if item.get("kind") == kind]
    return [at for at in found if at]


def retime(new: dict, park: list[dict], free: list[dict]) -> None:
    """The batch's timers after items moved, by the same rule the fold keeps them: the quiet
    window and its cap from the comments' own times, the check's from its own, and the
    urgency of what is left (a hand-over's, a freed review asking for changes, or none)."""
    pending, moved = new["pending"], {item.get("kind") for item in park + free}
    if not pending:
        for timer in shipwatch.TIMERS:
            new.pop(timer, None)
        return
    if "comment" in moved:
        said = stamps(pending, "comment")
        new.pop("first_at", None), new.pop("last_at", None)
        if said:
            new["first_at"], new["last_at"] = shipwatch.stamp(min(said)), shipwatch.stamp(max(said))
    if "ci" in moved:
        failed = stamps(pending, "ci")
        new.pop("ci_at", None)
        if failed:
            new["ci_at"] = shipwatch.stamp(max(failed))
    if any(ITEM_KINDS.get(str(item.get("kind"))) == COMMENTS for item in park):
        mine = [item for item in pending if str(item.get("handle")) in handed(new)]
        new.pop("urgent", None)
        if mine:
            new["urgent"] = shipreoffer.reason_of(mine)
    # a freed review is one the look has just confirmed still asks (`reconcile`)
    asking = [item for item in free if item.get("kind") == "review"]
    if asking and not new.get("urgent"):
        new["urgent"] = f"{asking[-1].get('author') or 'a reviewer'} asked for changes"


# ----- what the deck says, and offers -----

HANDED = "handed over: the drain tells the house on its next pass, and closes it once that turn ends"
HANDED_BASE = ("asked: the drain tells the house on its next pass to merge its base into its "
               "branch, with whatever review waits, and closes it once that turn ends")
NOTHING = ("Nothing to hand over: every comment and review was judged or posted, and the branch "
           "is up to date with its base.")
ALREADY = "Already handed over: the drain tells the house on its next pass."


def plain(said: str) -> str:
    """The verb's refusal as the deck says it: the two that speak of the verb in its own
    words, and any other (the house is still on its batch, the card is blocked, the change
    was declined) as it is, without the command's name in front."""
    if shipreoffer.NOTHING in said:
        return NOTHING
    if shipreoffer.ALREADY in said:
        return ALREADY
    return said[4:] if said.startswith("kb: ") else said

def turn_after(shipped: dict) -> int | None:
    """The event the batch told last starts after, by the marks `shipreoffer.held` reads; None
    when nothing marks that batch, so no event of its turn needs reading."""
    marks = [mark for mark in (shipped.get(shipreoffer.TURN_KEY), shipped.get(shipreoffer.RECORD_KEY))
             if isinstance(mark, dict) and mark.get("batch") == shipped.get("round")]
    return min(int(mark.get("after") or 0) for mark in marks) if marks and shipped.get("round") else None


def handover(card: dict, events: list[dict]) -> dict:
    """What his hand-over would give the house now, as the deck counts it: `comments` (a
    comment or a review asking for changes never told, or told and never judged), `checks`
    (a failing check kept untold, or told, never judged and failing at the last look),
    `his` (a send-back of his own told and never judged, c-663),
    `base` (the branch is behind its base or conflicts with it, or a merge of the base was
    asked and never judged), `asked` (a hand-over already waits for the drain) and `busy`
    (the batch its house is still on, whose items are not counted). What is counted is
    `shipreoffer.to_offer`, the same rule the verb's refusal reads. `events`: the turn's
    after `turn_after`, and every verdict (its handle and time are all that is read). The
    counts are the record's: the drain's own look, on the ask, decides what goes."""
    options = card.get("options") or {}
    shipped = options.get("shipping") or {}
    on = shipreoffer.held(shipped, events)
    told = {str(item.get("handle")): item for item in shipped.get("told") or []}
    open_ = shipreplies.unjudged(card, events)             # once: every told handle with no verdict
    left = {handle for handle in open_ if not on or told[handle].get("batch") != on}
    kinds = shipreoffer.to_offer(shipped, left)            # the rule the verb's refusal reads
    count = lambda kind: sum(1 for found in kinds.values() if ITEM_KINDS.get(found) == kind)  # noqa: E731
    return {"comments": count(COMMENTS), "checks": count(CHECKS),
            # his own send-backs the house was told and never judged (c-663)
            "his": sum(1 for found in kinds.values() if found == shipwatch.HIS_KIND),
            "base": shipreoffer.behind_or_conflicts(shipped) or kinds.get(shipreoffer.REBASE_HANDLE) is not None,
            "asked": bool(options.get("reoffer")),
            "busy": on if on and len(open_) > len(left) else None}
