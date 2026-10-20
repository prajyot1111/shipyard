"""Send back at shipping (c-663): his own notes on a shipping card, told to its house as one
more item of the card's batch.

His word (2026-10-05 and 06): a card at shipping only goes on to done, and when he looked at
one and wanted something changed his only way was to open the house's session and type. So
`kb ship <id> sendback --words "..."` (or `--words-file`), his alone, and the deck's Send
back on a shipping card, which is that verb run as him (`actions.act_send_back`):

1. **The ask** (`Board.send_back`, `options.sendback`): a list, one entry per send-back,
   each with its handle (`his-<n>`, counted on over everything the record ever held), who,
   when and his words. It is its own option, never part of `options.shipping`, so the
   drain's write of its record in the same pass cannot lose it, and only `Board.send_back`
   adds to it and `Board.take_sendback` takes from it (`Board.set_fields` refuses every
   actor). The card STAYS at shipping: no stage moves and no gate opens. Refused off
   shipping, on a blocked or archived card (the drain does not tend one, so it would wait
   unseen), on a card whose pull request was declined, and with no words.
2. **The fill** (`fill`, in `shipping.keep_sent_back`, every pass, with no look at the code
   host): each ask becomes an item of its own kind (`KIND`, `his`) in `pending`. SEVERAL
   SEND-BACKS ARE SEVERAL ITEMS, never one appended text: each gets its own verdict and its
   own row, and a second one sent after the house judged the first cannot take that row
   back to unjudged. An item of this kind answers to neither automatic-handling switch
   (`shipauto.ITEM_KINDS` does not name it, so `shipauto.settle` never parks one), and it is due
   on the pass that finds it (`shipwatch.due`). The asks it took are then taken off the
   option by their handles alone (`Board.take_sendback`), so one that landed meanwhile
   stays; an ask whose item is already in the record is taken and not filled twice.
3. **The batch** is an ordinary one. `fill` adds his items to `pending` and writes
   NOTHING ELSE: no hand-over mark (`options.shipping.reoffer` is the re-offer's alone), no
   timer. So the item is told the way any item is (the house resumed or started the
   ordinary way, a wait while the house is in a turn), and nothing about a send-back can
   stop a house or block a card: the close after a batch's turn and the unjudged block
   both hang off that mark (`keel/shipidle.py`), and without it the house is kept by the
   two-hour idle rule. Nor does a send-back perturb a re-offer: his ask is held (not
   taken, kept on the card, said there by `held`) only while that mark is open
   (`shipreoffer.is_reoffer`, read only) AND a strict listing shows the card's session
   with a process behind it (`shipping.keep_sent_back`, `shipidle.on_its_batch`). Once
   that turn has ended the re-offer is settled first (`shipidle.before_batch`, c-666) and
   the ask is taken. A house that is not running is on nothing: the ask is taken, his
   item resumes it the ordinary way, and the old mark is left behind the newer batch. A
   turn that ends with his item unjudged leaves it as any unjudged
   told item: the pane's "judging N", its row saying "told, not judged yet", and his
   hand-over (`kb ship <id> reoffer`) able to offer it again with his words as he wrote
   them (`shipreoffer.his_unjudged`). That batch is then his re-offer, under the re-offer's
   own rules, which this module does not touch.
4. **The answer** (`shipreplies.his_verdict`): valid with the commits that did it, or
   not-valid or deferred with the why; a reply is optional and is the house's answer to
   HIM. NOTHING IS POSTED for the item (`shipwatch.UNPOSTED_KINDS`): its row takes no post
   and no edit, is never among the replies his Ship posts, and is not counted as a reply
   waiting. The commits go out with his next Ship like any others.
"""

from __future__ import annotations

import copy
import re

from keel import shipreoffer, shipwatch

# The board's option for the asks waiting for the drain (`board.SENDBACK_OPTION`).
OPTION = "sendback"
KIND = shipwatch.HIS_KIND
PREFIX = "his-"
# Who may send back: he alone.
ACTORS = ("human",)
WORDS_MAX = 4000
SENT = ("sent back: the house is told this as its next item once it is free; "
        "nothing is posted")
ASKED_NOTE = ("The user sent this back to the house in person ({handle}): it is told as its next item "
              "once its house is free, the card stays at shipping, and nothing is posted for it: {words}")
FILLED_NOTE = "the user's send-back put in the batch ({handles})"


def numbered(handle) -> int:
    """`his-3` is 3; anything else is 0."""
    tail = str(handle or "")[len(PREFIX):]
    return int(tail) if str(handle or "").startswith(PREFIX) and tail.isdigit() else 0


def next_handle(options: dict) -> str:
    """The next send-back's handle: one past every one the card holds, asked or in its record."""
    shipped = options.get("shipping") or {}
    held = [ask.get("handle") for ask in options.get(OPTION) or []]
    held += [item.get("handle") for key in ("pending", "told", shipwatch.UNTOLD)
             for item in shipped.get(key) or []]
    return f"{PREFIX}{max([numbered(handle) for handle in held] or [0]) + 1}"


def refusal(stage: str, blocked: str | None, archived: bool, shipped: dict, words: str, change: str) -> str | None:
    """Why he may not send back now, or None."""
    if stage != "shipping":
        return f"is at {stage}; this send-back is for a card at shipping"
    if blocked:
        return f"is blocked ({blocked}): the drain does not tend it until the user unblocks it, so a send-back would wait unseen"
    if archived:
        return "is archived: the drain does not tend it, so a send-back would wait unseen"
    if shipped.get("state") == "declined":
        return f"had its {change} declined: nothing is answered there now"
    if not words.strip():
        return "needs the user's words: a send-back says what the user wants changed (--words or --words-file)"
    if len(words) > WORDS_MAX:
        return f"has words longer than {WORDS_MAX} characters"
    return None


# A line of his words that starts with a told item's handle and a colon (`c11: yes, move
# it`), as the deck's Answer on a prepared item leads them (c-723 review r1.F5).
NAMED = re.compile(r"^\s*([\w.-]+)\s*:", re.MULTILINE)


def answers(words: str, shipped: dict) -> list[str]:
    """The told items his send-back answers: each one a line of it starts with, by handle,
    in any case (`C11:` is c11, c-723 review r2.F6); `shipreplies.waiting_on_owner` ends
    the wait of these alone."""
    told = {str(item.get("handle")).lower(): str(item.get("handle")) for item in shipped.get("told") or []}
    return list(dict.fromkeys(told[name.lower()] for name in NAMED.findall(words or "") if name.lower() in told))


def ask(actor: str, words: str, at: str, handle: str) -> dict:
    return {"handle": handle, "by": actor, "at": at, "text": words.strip()}


def item_of(asked: dict) -> dict:
    """An ask as an item of the batch: his words whole, never cut."""
    return {"kind": KIND, "handle": str(asked.get("handle")), "author": "the user",
            "at": asked.get("at"), "text": str(asked.get("text") or "")}


def fill(shipped: dict, asks: list[dict]) -> tuple[dict, list[dict]]:
    """The record with each ask waiting in the batch as an item of his, and the items. An
    ask whose handle the record already holds is not filled again. The same record and no
    items when nothing is new. Nothing else is written: no mark, no timer."""
    held = {str(item.get("handle")) for key in ("pending", "told") for item in shipped.get(key) or []}
    items = [item_of(asked) for asked in asks if str(asked.get("handle")) not in held]
    if not items:
        return shipped, []
    new = copy.deepcopy(shipped)
    new["pending"] = list(new.get("pending") or []) + items
    if isinstance(new.get("facts"), dict):
        new["facts"]["waiting"] = len(new["pending"])
    return new, items


# Why what he sent is not on its way to the house, as the deck says it under his words.
HELD_DECLINED = "the {change} was declined, so nothing is told to the house"
HELD_ARCHIVED = "the card is archived, so the drain does not tend it; it is told once you unarchive it"
HELD_BLOCKED = "the card is blocked, so nothing is told to its house; it is told once you unblock it"


HELD_STOPPED = "you stopped its house, so it is told with your Resume"
HELD_PAUSED = "the drain is paused, so nothing is told to a house until it runs again"
# The one hold of this module's own: the house is ON a batch he handed over. It ends by
# itself when that turn ends (`shipidle.before_batch`, c-666) and when the house is no
# longer running (`shipping.keep_sent_back`). The sentence says what the ask waits FOR and
# never that the house is on the batch: the board cannot see the listing, and for a pass
# on which the listing failed that would be said of a house that may be gone. What is
# left is a house that sits listed and alive with a turn that never ends on the board (a
# lost Stop): his Resume (`actions.act_resume`) tells it in place and records a later
# turn, so the re-offer is over by the board's order.
HELD_HANDED = ("this waits for the batch you handed over: it is told once the house's turn on "
               "that batch ends, or once that house is no longer running. If the house sits idle "
               "and this still waits, Resume it")


def held(options: dict, blocked: bool, archived: bool, change: str, stopped: bool = False,
         paused: bool = False) -> str | None:
    """Why the drain is not telling what he sent now, or None when it tells it once the
    house is free. `stopped`: he stopped the house himself, and a batch waits for his Resume
    (`views.stop_holds`). `paused`: the drain is paused. The last reason is the one hold of
    this module's own: an ask not taken while its house is on a batch he re-offered
    (`shipping.keep_sent_back`)."""
    shipped = options.get("shipping") or {}
    if shipped.get("state") == "declined":
        return HELD_DECLINED.format(change=change)
    if archived:
        return HELD_ARCHIVED
    if blocked:
        return HELD_BLOCKED
    if stopped:
        return HELD_STOPPED
    if paused:
        return HELD_PAUSED
    if options.get(OPTION) and shipreoffer.is_reoffer(shipped):
        return HELD_HANDED
    return None


def waiting(options: dict, why: str | None = None) -> list[dict]:
    """What he sent back that the house has not been told yet, oldest first, as the deck says
    it: the asks the drain has not taken, and his items waiting in the batch, each with
    `held` (`why`: the sentence saying it is not on its way, or None)."""
    shipped = options.get("shipping") or {}
    found = [item for item in shipped.get("pending") or [] if item.get("kind") == KIND]
    found += [asked for asked in options.get(OPTION) or []
              if str(asked.get("handle")) not in {str(item.get("handle")) for item in found}]
    return [{"handle": str(one.get("handle")), "text": str(one.get("text") or ""), "at": one.get("at"),
             "held": why}
            for one in sorted(found, key=lambda one: numbered(one.get("handle")))]
