"""A re-offer (c-651): review a shipping card's house was never told, or was told and never
judged (c-654), offered to it again.

His word (2026-10-05): the cards at shipping whose reviewers wrote before the card entered
shipping were baselined by the watcher (c-604) and their comments never told (c-239: nine
review comments, told none), and many of those branches conflict with their base. So
`kb ship <id> reoffer [--rebase]`, his alone, ASKS for them, and the drain that holds the
house answers the ask on its next pass:

1. **The ask** (`Board.reoffer`, `options.reoffer`): who asked, when, and whether a rebase
   was asked for. It is its own option, not part of `options.shipping`, so the drain's
   write of its record in the same pass can never lose it. The verb refuses a card that is
   not at shipping, a blocked or archived one, one already asked, and one with nothing to
   offer (`refusal`). Leaving shipping clears it (`Board._move`), and so do a block and an
   archive, with a note (`Board._drop_reoffer`). What the house is STILL ON is not
   something to offer (`held`, c-654 review): the batch told last, while its own turn has
   not ended. Asked mid-turn, those items were queued and told again, and the verdicts the
   house had just written were dropped by their rows' new `told_at`.
2. **The fill** (`fill`, in `shipping.tend`): the drain looks at the pull request at once,
   folds the look as always, and puts into `pending` every comment of that look and every
   review asking for changes that was never told, or was told and has no verdict since
   (`shipreplies.unjudged`, c-654: told is not judged; told again, its row starts afresh),
   never posted and is not waiting already, as the watcher's own items (`shipwatch.comment_item`, handles prefixed by repo for a
   pull request other than the primary). The adapter's sight already leaves out a bot's
   comments, the tracker's link comment among them, and the author's own (`packs/work`'s
   `prsight.comments_of`), so what is left is the human reviewers'. With `--rebase`, when an
   earlier `rebase` item was left unjudged, or when nothing else is left, one `rebase` item asks the house to bring its branch up to
   its base by MERGING the base in (never a rebase or a force push: his Ship's push is a
   plain fast-forward, `shipround.REBASE`). The base is his `options.base`, else the
   destination the pull request itself names (the sight's `base`, kept as the record's);
   with neither, the rebase is refused with a note, never guessed (`NO_BASE_NOTE`), and a
   plain re-offer left with only a branch behind that unnamed base says so
   (`BEHIND_NO_BASE`), never that the branch is up to date. The
   batch is due at once (`urgent`), and the ask is cleared. The items offered AGAIN are
   kept on the mark (`again`), and one the house judges before the batch is told (it can
   wait for a slot) is dropped from it then (`drop_judged`). A look that fails keeps the ask
   for the next look at the normal cadence; the third failed look clears it with a note
   naming the failure (`failed`), each written only while the same ask is still on a card
   at shipping (`Board.keep_reoffer`).
3. **The batch** (`on_batch`, in `shipping.deliver`): every told batch keeps where its turn
   starts (`options.shipping.turn`: its number and `after`, the newest event on the card
   before it was told), and the one that carries a filled re-offer is marked
   `options.shipping.reoffer` with its `batch`, `told_at`, and the same `after`.
4. **The stop** (`batch_turn`, in `keel/shipidle.py`): by the board's own order of events,
   never two clocks, the first turn start after `after` is the batch's own (`started`), and
   the first `Stop` of that session after it ends it (`ENDED`). Then the drain closes the
   house as idle (`closed_at`), his explicit word: an idle house does not hold memory. A
   `SessionEnd` of that session says the house itself is gone (`EXITED`): nothing is left
   to close, and the re-offer is over. Once any later turn has started (his Talk, his
   Resume, a newer batch), or he has taken the house by voice or Drop in (a hold the board
   records, `HOLDS`), the re-offer is over (`done_at`) and never closes anything. The deck
   says the close is due now (`views.ship_idle`). Its next batch resumes it. A normal batch
   keeps the two-hour idle close. These marks are written by `Board.mark_reoffer` alone,
   which re-reads the record in its transaction, so a Ship landing meanwhile keeps what it
   posted.
5. **What it left** (c-654, `keel/shipidle.py`): a turn that ended is not an answer. The
   batch's items with no verdict since they were told are kept on the mark (`unjudged`),
   said on the card as N of M, and the card is blocked for him with them named, under a
   mark of its own (`UNJUDGED_MARK`) that the watcher looks past for a merge or a decline
   (`awaits_him`). Nothing tells that batch again by itself, so a house that judges nothing
   can never loop: his next `kb ship <id> reoffer` is the one way they are offered again
   (the fill above). A normal batch is not settled this way: its house is kept two hours
   so a later turn can finish the judging (`keel/shipidle.py` says why).
6. **A batch due behind it** (c-666, `shipidle.before_batch`): the watcher runs before the
   idle step, so a batch told on the pass after that turn ended moved `round` past the
   mark and the re-offer was never settled. So the watcher, about to tell a batch (or with
   a send-back of his waiting) while the mark is open and its turn has ended, settles the
   re-offer first, in that pass, with the idle step's own function on a strict listing:
   closed or gone exactly as in 4 and 5 (a listed row with no process is gone); nothing
   settled and nothing told while the listing or the stop fails; and, where the close is
   refused for a job of the house's own or a terminal, the mark over (`done_at`) and one
   note stating that fact and naming what has no verdict yet, with no stop and no block,
   since that house may still be judging. Any other refusal writes nothing
   (`keel/shipidle.py` lists them by kind). Nothing is kept from one pass to the next.
   Every write of the mark's own fields goes through `Board.mark_reoffer`.

The deck's hand-over is this same ask (c-655, `actions.act_hand_over`): `kb ship <id>
reoffer` run as him by a tap on the shipping card. Since c-655 a kind of review whose
automatic handling is off is kept on the card untold (`options.shipping.untold`,
`keel/shipauto.py`), and the fill gives the house those too: the comments and reviews as
the look shows them now, and a failing check kept untold, which the fold has just
confirmed still fails. An untold item is never "done" (`handles_done`), even under a
handle the house was told and judged before, and is never dropped as judged meanwhile.
"""

from __future__ import annotations

import copy
from datetime import datetime

from keel import shipwatch, views

# The record's own key for a filled re-offer (`options.shipping.reoffer`); the ask is the
# board's `options.reoffer` (`board.REOFFER_OPTION`).
RECORD_KEY = "reoffer"
# Where the batch told last starts on the board (`options.shipping.turn`: `{batch, after}`,
# written for EVERY batch, c-654 review), so its own turn is found by the board's order.
TURN_KEY = "turn"
# The mark of the block a turn that left items unjudged puts on the card (`board.MARKS`).
UNJUDGED_MARK = "unjudged"
# Who may ask: he alone. The ask names no item; the drain's own look does.
REOFFER_ACTORS = ("human",)
REBASE_KIND = REBASE_HANDLE = "rebase"
# Looks that may fail before the ask is given up, said on the card.
FAILED_LOOKS = 3
ASKED_NOTE = ("You re-offered the review this house was never told{rebase}: the drain looks "
              "at the {change} on its next pass and tells the house at once, and stops it once "
              "its turn on that batch ends, since an idle house does not hold memory")
FILLED_NOTE = "re-offer: {n} {items} put in the batch ({handles})"
EMPTY_NOTE = "re-offer: nothing to offer ({why})"
FAILED_NOTE = ("re-offer dropped: the drain could not look at the {change} {n} times in a row "
               "(last: {why}); ask again once it can")
JUDGED_NOTE = ("re-offer: {handles} left out of the batch: the house judged {them} between the "
               "re-offer and the tell")
STILL_ON = ("the house is still on batch {batch}: its turn on the {n} {items} it was told there "
            "has not ended, so {they} not offered again yet; ask again once it has")
NO_BASE_NOTE = ("re-offer: --rebase refused: neither options.base nor the {change}'s own "
                "destination names the branch's base, and Shipyard never guesses it; set options.base "
                "and ask again")
# A plain re-offer with nothing to offer on a branch behind a base nothing names (with no base
# the conflict check has nothing to check against): said as it is, never "up to date"
# (EMPTY_NOTE's `why`).
BEHIND_NO_BASE = ("no comments to re-offer, and the branch is behind its base, "
                  "but neither options.base nor the {change}'s own destination names that base, so "
                  "there is none to ask a rebase against; set options.base and ask again")
# The verb's two refusals the deck's hand-over says in its own words (`shipauto.plain`, c-655).
ALREADY = "a re-offer is already asked and waits for the drain's next pass"
NOTHING = "nothing to re-offer"
NOTHING_WHY = (": every comment and review seen was judged or posted, and the "
               "branch neither conflicts with nor is behind its base (--rebase asks anyway)")
# Why `fill` wrote no rebase item for want of a base: his --rebase refused, or a plain
# re-offer's branch behind a base nothing names.
REBASE_REFUSED, BEHIND_UNKNOWN_BASE = "refused", "behind"
# What the board's events say a turn started: a resume or a tell (`record_resume`), a session.
TURN_STARTS = ("resume", "session")
# His own turns the board records as a hold taken (c-651 review): voice talking to the house
# (`Board.hold_voice`) or his Drop in at a terminal (`options.dropin_hold`).
HOLDS = (views.VOICE_HOLD_OPTION, views.DROPIN_HOLD_OPTION)
# Where a re-offered batch's own turn stands. ENDED is not "answered" (c-654): what the house
# judged in it is the verdicts' to say (`shipreplies.unjudged`).
WAITING, ENDED, EXITED, OVER = "waiting", "ended", "exited", "over"
TURN_ENDS = {"Stop": ENDED, "SessionEnd": EXITED}


# ----- the ask, as the verb weighs it -----

def handles_done(shipped: dict, unjudged=frozenset()) -> set[str]:
    """Handles the house was told and judged, his Ship posted, or that are waiting to go.
    `unjudged`: the told handles with no verdict since (`shipreplies.unjudged`, c-654),
    which are not done."""
    done = {str(item.get("handle")) for item in shipped.get("told") or []} - set(unjudged)
    done |= set((shipped.get("posted") or {}).keys())
    # collected and not told (c-655): never done, even under a handle told and judged before
    done -= untold_handles(shipped)
    return done | {str(item.get("handle")) for item in shipped.get("pending") or []}


def untold_handles(shipped: dict) -> set[str]:
    """What waits untold because its kind's automatic handling is off (`keel/shipauto.py`)."""
    return {str(item.get("handle")) for item in shipped.get(shipwatch.UNTOLD) or []}


def seen_handles(shipped: dict) -> set[str]:
    """Every comment and changes-requested review the record says was seen, by its handle:
    the primary's (`seen`) unprefixed, each other pull request's (`seen_other`) as
    `<repo>.<handle>`."""
    sources = [("", shipped.get("seen") or {})]
    sources += [(f"{repo}.", seen) for repo, seen in (shipped.get("seen_other") or {}).items()]
    out = set()
    for prefix, seen in sources:
        out |= {f"{prefix}c{number}" for number in seen.get("comments") or []}
        out |= {f"{prefix}review-{shipwatch.slug(author)}"
                for author, state in (seen.get("reviews") or {}).items() if state == "changes_requested"}
    return out


def never_told(shipped: dict, unjudged=frozenset()) -> set[str]:
    """The comments and reviews the record saw that are not done (`handles_done`), a told
    and never judged one among them whether or not `seen` still lists it, and, once a look
    has said what is on the code host (`shipwatch.ON_HOST`, c-655 review), only those still
    there: one deleted, resolved or withdrawn since is nothing to offer."""
    open_ = {str(item.get("handle")) for item in shipped.get("told") or []
             if item.get("kind") in ("comment", "review")} & set(unjudged)
    found = (seen_handles(shipped) - handles_done(shipped, unjudged)) | open_
    return found & set(shipped[shipwatch.ON_HOST]) if shipwatch.ON_HOST in shipped else found


def to_offer(shipped: dict, unjudged=frozenset()) -> dict:
    """`{handle: kind}`: what an ask would give the house by the record, the ONE rule the
    verb's refusal and the deck's count both read, so they cannot disagree (c-655 review).
    A comment or a review asking for changes seen and not done (`never_told`, which holds a
    told and never judged one to the code host too); a check told, never judged and failing
    at the last look (`failing_checks`); a merge of the base asked and never judged; and
    whatever waits untold (`keel/shipauto.py`). Nothing already waiting in the batch or
    posted is among them. `unjudged`: the told handles with no verdict since, but for the
    batch the house is still on."""
    told = {str(item.get("handle")): str(item.get("kind")) for item in shipped.get("told") or []}
    out = {handle: told.get(handle) if told.get(handle) == "review" else "comment"
           for handle in never_told(shipped, unjudged)}
    out.update({handle: "ci" for handle in failing_checks(shipped) & set(unjudged)})
    if REBASE_HANDLE in unjudged:
        out[REBASE_HANDLE] = REBASE_KIND
    # his own send-back, told and never judged (c-663): his to offer again
    out.update({str(item.get("handle")): shipwatch.HIS_KIND for item in his_unjudged(shipped, unjudged)})
    # what already waits in the batch (a hand-over filled and not told yet) or was posted is
    # not offerable, told and never judged or not: the fill would give nothing for it
    taken = {str(item.get("handle")) for item in shipped.get("pending") or []}
    taken |= set((shipped.get("posted") or {}).keys())
    out = {handle: kind for handle, kind in out.items() if handle not in taken}
    out.update({str(item.get("handle")): str(item.get("kind")) for item in shipped.get(shipwatch.UNTOLD) or []})
    return out


def his_unjudged(shipped: dict, unjudged=frozenset()) -> list[dict]:
    """His own send-backs the house was told and never judged (c-663,
    `keel/shipsendback.py`), as items to tell again: the told item itself, his words whole,
    without the batch it was told in. No code host holds one for a look to find."""
    return [{key: value for key, value in item.items() if key not in ("batch", "told_at")}
            for item in shipped.get("told") or []
            if item.get("kind") == shipwatch.HIS_KIND and str(item.get("handle")) in set(unjudged)]


# Why no merge of the base is asked of a house whose worktree its own branch on the remote
# has left behind (c-653): a merge on top of that history is one more thing to untangle.
OUT_OF_STEP = ("the branch is out of step with its {change}'s branch, so its base is not merged in "
               "now: bring the worktree in line first (the card shows the command), then ask again")


def out_of_step(shipped: dict) -> bool:
    """Is a worktree behind its own pull request's branch (`options.shipping.local.behind`)."""
    return bool((shipped.get("local") or {}).get("behind"))


def base_moved(shipped: dict) -> bool:
    return bool((shipped.get("local") or {}).get("conflicts")
                or (shipped.get("facts") or {}).get("behind"))


def behind_or_conflicts(shipped: dict) -> bool:
    """Is a merge of the base something to offer by itself: the branch is behind its base
    or conflicts with it, and is not out of step with its own branch on the remote (then
    nothing adds the item: not the fill, not the deck's count)."""
    return base_moved(shipped) and not out_of_step(shipped)


def still_on(batch: int, count: int) -> str:
    one = count == 1
    return STILL_ON.format(batch=batch, n=count, items="item" if one else "items",
                           they="it is" if one else "they are")


def refusal(shipped: dict, waiting: bool, rebase: bool, change: str,
            unjudged=frozenset(), on: int | None = None, busy: int = 0) -> str | None:
    """Why the verb may not ask now (`waiting`: an ask is already on the card), or None. A
    card never looked at yet may be asked: its first look decides. Comments the record saw
    may include a bot's from an older look; the drain's fill, over a fresh look, is what
    decides what goes. `unjudged`: what the house was told and never judged, which is
    something to offer (c-654). `on` and `busy`: the batch its house is still on (`held`) and
    how many of its items have no verdict yet; they are not something to offer, and an ask
    with nothing else is refused saying so."""
    if waiting:
        return ALREADY
    if shipped.get("state") == "declined":
        return f"its {change} was declined: nothing is answered there now"
    if rebase and out_of_step(shipped):
        return OUT_OF_STEP.format(change=change)
    if rebase or "seen" not in shipped:
        return None
    if to_offer(shipped, unjudged) or behind_or_conflicts(shipped):
        return None                   # the one rule the deck's count reads too (c-655 review)
    if on and busy:
        return still_on(on, busy)
    if out_of_step(shipped) and base_moved(shipped):
        return OUT_OF_STEP.format(change=change)     # the base merge was all there was to offer
    return NOTHING + NOTHING_WHY


def ask(actor: str, rebase: bool, at: str) -> dict:
    return {"by": actor, "at": at, "rebase": bool(rebase)}


def failed(asked: dict, why: str) -> dict | None:
    """The ask after one more failed look, or None once `FAILED_LOOKS` have failed."""
    count = int(asked.get("failed") or 0) + 1
    return None if count >= FAILED_LOOKS else dict(asked, failed=count, why=why)


# ----- the fill, on the drain's look -----

def rebase_item(shipped: dict, base: str, at: datetime) -> dict:
    local, facts = shipped.get("local") or {}, shipped.get("facts") or {}
    return {"kind": REBASE_KIND, "handle": REBASE_HANDLE, "base": base,
            "behind": facts.get("behind"), "conflicts": bool(local.get("conflicts")),
            "at": shipwatch.stamp(at)}


def offered(shipped: dict, sight: dict, at: datetime, unjudged=frozenset()) -> list[dict]:
    """The look's comments and changes-requested reviews never judged (never told, or told
    with no verdict since, `unjudged`), posted or waiting, as the watcher's own items; and a
    check failing on this look that waits untold or was told and never judged."""
    done, items = handles_done(shipped, unjudged), []
    for part, _primary, prefix in shipwatch.labelled_parts(sight):
        for found in part.get("comments") or []:
            items.append(shipwatch.comment_item(found, at, part, prefix))
        for review in part.get("reviews") or []:
            if review.get("state") == "changes_requested":
                items.append(shipwatch.with_repo(
                    {"kind": "review", "handle": f"{prefix}review-{shipwatch.slug(review['author'])}",
                     "author": review["author"], "state": "changes_requested",
                     "at": review.get("state_at") or review.get("at") or shipwatch.stamp(at)}, part))
        # a check failing on this look that waits untold, or was told and never judged
        # (c-655 review): one the look shows passing is not offered
        check = check_item(part, prefix, at)
        if check and check["handle"] in untold_handles(shipped) | set(unjudged):
            items.append(check)
    items += his_unjudged(shipped, unjudged)
    return [item for item in items if item["handle"] not in done]


def check_item(part: dict, prefix: str, at: datetime) -> dict | None:
    """The failed check on one pull request's head as the look shows it, as the watcher's
    own item (`shipwatch.fold_ci`), or None while its checks pass, run or are none."""
    ci = part.get("ci") or {}
    if ci.get("state") != "failed":
        return None
    when = min(shipwatch.parse(ci.get("at")) or at, at)
    return shipwatch.with_repo({"kind": "ci", "handle": f"{prefix}ci", "state": "failed",
                                "name": ci.get("name"), "url": ci.get("url"),
                                "at": shipwatch.stamp(when)}, part)


def failing_checks(shipped: dict) -> set[str]:
    """The handles of the checks the last look saw failing, by the record's `facts`: `ci`
    for the primary pull request, `<repo>.ci` for another (a record from before `facts.prs`
    marked the primary takes its first as it)."""
    facts = shipped.get("facts") or {}
    prs = [pr for pr in facts.get("prs") or [] if isinstance(pr, dict)]
    if not prs:
        return {"ci"} if facts.get("ci") == "failed" else set()
    marked = any(pr.get("primary") for pr in prs)
    return {("" if (pr.get("primary") if marked else index == 0) else f"{pr.get('repo') or 'pr'}.") + "ci"
            for index, pr in enumerate(prs) if pr.get("ci") == "failed"}


def fill(shipped: dict, sight: dict, asked: dict, base: str | None,
         at: datetime, unjudged=frozenset()) -> tuple[dict, list[dict], str | None]:
    """The record with the re-offered items waiting and due at once, the items, and why a
    rebase was wanted but not written for want of a base (`base`: his `options.base` or the
    pull request's own destination, never a guess): `REBASE_REFUSED` for his --rebase,
    `BEHIND_UNKNOWN_BASE` for a plain re-offer's branch behind its base, else None.
    The record unchanged and no items when there is nothing to offer. `unjudged`: the told
    handles with no verdict since (c-654), offered again; a `rebase` among them asks again."""
    items = offered(shipped, sight, at, unjudged)
    wanted = (asked.get("rebase") or REBASE_HANDLE in unjudged
              or (not items and behind_or_conflicts(shipped)))
    if wanted and base and REBASE_HANDLE not in {str(i.get("handle")) for i in shipped.get("pending") or []}:
        items.append(rebase_item(shipped, base, at))
    refused = None
    if wanted and not base:
        refused = REBASE_REFUSED if asked.get("rebase") else BEHIND_UNKNOWN_BASE
    if not items:
        # nothing of what waited untold is on the code host any more (c-655 review)
        return ({key: value for key, value in shipped.items() if key != shipwatch.UNTOLD}
                if shipwatch.UNTOLD in shipped else shipped), [], refused
    new = copy.deepcopy(shipped)
    new["pending"] = list(new.get("pending") or []) + items
    new["urgent"] = reason_of(items)
    # the untold items are in the batch now, or are gone from the code host (c-655)
    new.pop(shipwatch.UNTOLD, None)
    # an untold item under a handle told before is new words or a new failure, not "again"
    again = {str(item.get("handle")) for item in shipped.get("told") or []} - untold_handles(shipped)
    new[RECORD_KEY] = {"by": asked.get("by"), "asked_at": asked.get("at"),
                       "rebase": bool(asked.get("rebase")), "filled_at": shipwatch.stamp(at),
                       "items": [item["handle"] for item in items],
                       # told before and offered again: dropped if judged before the tell
                       "again": [item["handle"] for item in items if item["handle"] in again]}
    return new, items, refused


def drop_judged(shipped: dict, judged: set[str]) -> tuple[dict, list[str]]:
    """A filled re-offer not told yet, without the items offered AGAIN (`again`) that the
    house has judged since the fill (`judged`: the handles with a verdict now), and those
    handles. The batch can wait for a slot or for the house's turn to end, and a verdict
    recorded meanwhile stands: told again, the item's row would start afresh and that
    verdict be lost (c-654 review). With nothing of the re-offer left, its mark and its
    urgency go too, and whatever else waits keeps its own timers."""
    mark = shipped.get(RECORD_KEY) or {}
    if not mark.get("filled_at") or mark.get("batch"):
        return shipped, []
    gone = [handle for handle in mark.get("again") or [] if handle in judged]
    if not gone:
        return shipped, []
    new = copy.deepcopy(shipped)
    new["pending"] = [item for item in new.get("pending") or [] if item.get("handle") not in gone]
    kept = [handle for handle in mark.get("items") or [] if handle not in gone]
    mine = [item for item in new["pending"] if item.get("handle") in kept]
    if mine:
        new[RECORD_KEY] = dict(mark, items=kept, again=[h for h in mark["again"] if h not in gone])
        new["urgent"] = reason_of(mine)
    else:
        new.pop(RECORD_KEY, None)
        new.pop("urgent", None)
    return new, gone


def reason_of(items: list[dict]) -> str:
    """Why the batch goes now, as the house's prompt and the card's note say it."""
    his = sum(1 for item in items if item["kind"] == shipwatch.HIS_KIND)
    count = sum(1 for item in items if item["kind"] != REBASE_KIND) - his
    said = [f"re-offered {count} review {'item' if count == 1 else 'items'} you have not judged"] if count else []
    if his:
        said.append(f"sent {his} {'item' if his == 1 else 'items'} of their own back to you")
    if any(item["kind"] == REBASE_KIND for item in items):
        said.append("asked for your branch brought up to its base by merging it in")
    return "the owner " + " and ".join(said)


# ----- the batch, and its end -----

def on_batch(told: dict, at: datetime, after: int) -> dict:
    """The record a batch was just taken into: every batch keeps where its turn starts
    (`TURN_KEY`: its number and `after`, the newest event on the card before the tell), and a
    filled re-offer not yet told is marked as told in this batch with the same `after`, so
    its turn (and only its turn) is found by the board's own order."""
    told = dict(told, **{TURN_KEY: {"batch": told.get("round"), "after": int(after or 0)}})
    mark = told.get(RECORD_KEY) or {}
    if not mark.get("filled_at") or mark.get("batch"):
        return told
    return dict(told, **{RECORD_KEY: dict(mark, batch=told.get("round"), told_at=shipwatch.stamp(at),
                                          after=int(after or 0))})


def is_reoffer(shipped: dict) -> bool:
    """Is the batch told last a re-offer still open: not closed for, not over?"""
    mark = shipped.get(RECORD_KEY) or {}
    return (bool(mark.get("batch")) and mark["batch"] == shipped.get("round")
            and not mark.get("closed_at") and not mark.get("done_at"))


def turn_done(shipped: dict, events: list[dict]) -> bool:
    """Is the batch told last an open re-offer whose own turn has ended, or whose session
    has (`batch_turn` ENDED or EXITED): the one the idle step settles on its next run?"""
    return is_reoffer(shipped) and batch_turn(shipped[RECORD_KEY], events)[0] in (ENDED, EXITED)


def held(shipped: dict, events: list[dict], working: bool = False) -> int | None:
    """The told batch its house is still on, whose items are not offered again (c-654
    review: re-queued mid-turn, they were told again and the verdicts the house was writing
    thrown away): the batch told last, while the board shows its own turn not ended
    (`batch_turn` WAITING, by `TURN_KEY`, or by the re-offer's mark for one told before every
    batch kept it), or while the harness lists the house in a turn (`working`, which only
    the drain can say). None when nothing was told, or its turn is over."""
    batch = shipped.get("round")
    if not batch or not any(item.get("batch") == batch for item in shipped.get("told") or []):
        return None
    if working:
        return batch
    mark = next((one for one in (shipped.get(TURN_KEY), shipped.get(RECORD_KEY))
                 if isinstance(one, dict) and one.get("batch") == batch), None)
    return batch if mark is not None and batch_turn(mark, events)[0] == WAITING else None


def awaits_him(events: list[dict]) -> bool:
    """Is the card's standing block the unjudged one (`UNJUDGED_MARK`)? The newest block on
    record says: such a card needs his re-offer, and is still looked at for a merge or a
    decline (`shipping.upkeep`), which a blocked card otherwise is not."""
    for event in reversed(events):
        if event["kind"] == "block":
            return bool((event.get("data") or {}).get(UNJUDGED_MARK))
        if event["kind"] == "unblock":
            return False
    return False


def batch_turn(mark: dict, events: list[dict]) -> tuple[str, dict | None]:
    """Where the re-offered batch's own turn stands, over the card's events oldest first:
    WAITING (not started, or not ended), ENDED (its first Stop came, no turn since), EXITED
    (the harness said its session ended, with or without a Stop first: the house is gone) or
    OVER (another turn started after it, or he took the house by voice or Drop in since it
    was told); and the event that started it, as `{event, at}`."""
    after, started, state = int(mark.get("after") or 0), None, WAITING
    for event in events:
        if event["id"] <= after:
            continue
        data = event.get("data") or {}
        if is_hold(event):
            return OVER, (start_of(started) if started else None)
        if event["kind"] in TURN_STARTS:
            if started is None:
                started = event
            elif not same_start(started, event):
                return OVER, start_of(started)
        elif started is not None and state != EXITED:
            state = turn_end(data, session_of(started)) or state
    return state, (start_of(started) if started else None)


def is_hold(event: dict) -> bool:
    """A hold taken, his voice or his Drop in: a turn of his own (its release is not)."""
    options = (event.get("data") or {}).get("options") if event["kind"] == "set" else None
    return isinstance(options, dict) and any(isinstance(options.get(key), dict) for key in HOLDS)


def same_start(started: dict, event: dict) -> bool:
    """A resume that minted a new session records it in a `session` event right after: the
    same turn start, not another one."""
    return (started["kind"] == "resume" and event["kind"] == "session"
            and session_of(event) == session_of(started))


def session_of(event: dict) -> str | None:
    return (event.get("data") or {}).get("session_id")


def turn_end(data: dict, session_id: str | None) -> str | None:
    """ENDED or EXITED when this hook is the batch's own session ending its turn or itself."""
    # a Stop the hook blocked did not end the turn: the house carried on (c-607 review)
    if not session_id or data.get("session_id") != session_id or data.get("stop_blocked"):
        return None
    return TURN_ENDS.get(data.get("hook"))


def start_of(event: dict) -> dict:
    return {"event": event["id"], "at": event.get("at")}
