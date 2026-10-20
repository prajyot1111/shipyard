"""The pull request watcher's rules (lane SHIP): how often to look, what is new, when it goes.

Pure functions over one card's record, `options.shipping`, and what the adapter saw on the
code host this time (a SIGHT, printed by the adapter's `ship <id> poll`). Nothing here
reads the network, the board or the clock: `keel/shipping.py` does all three and calls
these, which is what lets the tests drive a day of review in a loop of minutes.

A sight, in the engine's words (the adapter translates its code host into these):

    {"state": "open" | "merged" | "declined", "url", "head", "base", "behind", "approvals",
     "comments": [{"id", "author", "at", "text", "path", "line", "parent"}],   # others' only
     "reviews":  [{"author", "state": "approved" | "changes_requested", "at", "state_at"?}],
     "ci": {"state": "passed" | "failed" | "running" | "none", "name", "url", "at"}}

A card with a pull request in more than one repo (SH-10, `options.prs`) is seen as
`{"state", "url", "head", "prs": [sight, ...]}`: one sight per pull request, each with its
`repo` and `pr`, the card's primary one marked `primary`. The fold keeps what it has seen
per pull request, and the batch, its debounce and its round are ONE across them. A handle
from a pull request other than the primary starts `<repo>.` (`webapp-react.c21`), which is
how the adapter sends its reply to the right one. The card merges when ALL have merged and
is declined when ANY was.

The record (`options.shipping`), which only the drain and he write (`board.SHIPPING_ACTORS`):

    since, round, answered_at                 the card's own history on this pull request
                                              (`round`: how many batches were told)
    seen {comments, reviews, ci}              what has been looked at; absent until the
                                              first look, which is a BASELINE: what was
                                              there by `since` is seen, nothing of it is
                                              flagged; anything later is new (c-604)
    seen_other {repo: {comments, reviews, ci}}  the same for each pull request but the
                                              primary; one that joins later is baselined
    pending [item], first_at, last_at,        the batch waiting, and its timers
    urgent, ci_at
    untold [item]                             what waits and is NOT told: the items of a
                                              kind whose automatic handling is off
                                              (c-655, `keel/shipauto.py`), kept until
                                              he hands them over or turns the kind on
    on_host [handle]                          the comments and reviews asking for changes
                                              the last look showed, so one seen once and
                                              since deleted, resolved or withdrawn is not
                                              counted or asked for (c-655 review)
    told [item + batch, told_at]              every item handed to the house (c-600): the
                                              rows of the standing batch the deck draws
    posted {handle: digest}, shipped_at       what his Ship posted, and when (`Board.ship`)
    local {ahead, behind, unchecked,          the git read of the card's worktrees (each
                                              pass, and his Ship right after its push, c-660):
           conflicts, diverged {ahead,        both sides against the pull request's branch,
           behind}, said, by_hand}            diverged when both, the one sentence said for
                                              it, and the commands that bring each such
                                              worktree in line by hand, or why there are
                                              none (c-653, `shipping.local_facts`,
                                              `keel/shipstep.py`)
    activity_at                               the newest thing seen move
    base                                      the branch the primary pull request merges
                                              into, as its last look named it (`base`
                                              in the sight); what the conflict check and
                                              a re-offer's rebase use when the card has
                                              no `options.base` (c-651 review)
    reoffer {by, asked_at, rebase, filled_at, items, batch, told_at, after,
             started, closed_at, done_at, unjudged}
                                              a re-offer the drain filled, the batch that
                                              told it, the turn it started, its house's
                                              close or its end (c-651,
                                              `keel/shipreoffer.py`), and the handles its
                                              turn left with no verdict (c-654)
    facts {state, comments, approvals, ci, behind, waiting, draft}   what the deck's chip
                                              says; with several pull requests, summed,
                                              plus `prs`, each one's own

An item is {kind, handle, ...}: `c<id>` for a comment (a reply to it goes under it),
`review-<who>` for a submitted review and `ci` for a failed check (a reply to either is a
general comment). Two kinds come from him and not from the code host, and nothing is ever
posted for either (`UNPOSTED_KINDS`): `rebase` (c-651, `keel/shipreoffer.py`) and `his`,
his own send-back at shipping (`his-<n>`, c-663, `keel/shipsendback.py`). The handle is the row id the round's replies batch uses. A comment's
text is kept to TEXT_MAX; every comment's WHOLE text is in the card's
`comments/<handle>.md` (`whole_texts`), and a cut text ends with a marker naming that file.

THE DEBOUNCE (c-600, his numbers 2026-09-30): comments and failed checks wait for a QUIET
window of 5 minutes, reset by every new one, capped at 30 minutes from the first waiting
one; a SUBMITTED review asking for changes (or an approval that came with comments) goes
at once; a check that passes again before it goes is taken back. One batch takes every
waiting item, and what arrives while the house works on it waits for the next.

THE CADENCE (c-600): every 2 minutes while items wait; every 3 while told items are not
shipped yet or the pull request moved in the last hour (the approve counts); every 10 in
work hours; hourly at night and at weekends. One look is three or four calls to the host,
so a card with items waiting costs about 120 calls an hour, and only while they wait.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

QUIET = timedelta(minutes=5)
CAP = timedelta(minutes=30)
RECENT = timedelta(hours=1)
WAITING = timedelta(minutes=2)
FAST = timedelta(minutes=3)
NORMAL = timedelta(minutes=10)
SLOW = timedelta(hours=1)
# Kept on the card: a longer comment is cut to fit with CUT_MARK, and its whole text is in
# the card's `comments/<handle>.md` (`whole_texts`, written by `keel/shipping.py`).
TEXT_MAX = 2000
COMMENTS_DIR = "comments"
CUT_MARK = "[cut: full text in comments/{name}]"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HOURS_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")
TIMERS = ("first_at", "last_at", "urgent", "ci_at")
# The record's list of items collected and not told (c-655, `keel/shipauto.py`).
UNTOLD = "untold"
# The handles of the comments and the reviews asking for changes the last look showed
# (c-655 review): what was seen once and is gone from the code host is not counted as waiting.
ON_HOST = "on_host"
# His own send-back at shipping (c-663, `keel/shipsendback.py`): an item that comes from him,
# is told whatever the automatic-handling switches say, and goes on the pass that finds it.
HIS_KIND = "his"
HIS_DUE = "the owner sent {n} {items} of their own back to you"
# The kinds that answer no reviewer: nothing is ever posted for one, so it is never among
# the replies his Ship posts.
UNPOSTED_KINDS = ("rebase", HIS_KIND)


@dataclass(frozen=True)
class WorkHours:
    """When he works, in minutes of the day [start, end) on these weekdays (Monday is 0),
    read in `tz` (None: this machine's local time). `[keel] work_hours` and `work_days`."""
    start: int = 9 * 60
    end: int = 19 * 60
    days: tuple = (0, 1, 2, 3, 4)
    tz: tzinfo | None = None

    @classmethod
    def parse(cls, hours: str, days: str) -> "WorkHours":
        """`"09:00-19:00"` and `"mon-fri"` (or `"mon,wed,fri"`); ValueError on anything else."""
        match = HOURS_RE.match(str(hours).strip())
        if not match:
            raise ValueError(f"work_hours is HH:MM-HH:MM, not {hours!r}")
        h1, m1, h2, m2 = (int(part) for part in match.groups())
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if not (0 <= start < end <= 24 * 60):
            raise ValueError(f"work_hours must start before it ends within one day: {hours!r}")
        return cls(start=start, end=end, days=day_list(days))


def day_list(text: str) -> tuple:
    picked = []
    for part in str(text).lower().replace(" ", "").split(","):
        first, _, last = part.partition("-")
        if first not in DAYS or (last and last not in DAYS):
            raise ValueError(f"work_days names days as mon..sun, not {text!r}")
        a, b = DAYS.index(first), DAYS.index(last or first)
        picked += list(range(a, b + 1)) if a <= b else list(range(a, 7)) + list(range(0, b + 1))
    return tuple(sorted(set(picked)))


def parse(text) -> datetime | None:
    """An ISO stamp as an aware datetime; None for anything unreadable."""
    try:
        at = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.astimezone()


def stamp(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


# ----- how often -----

def in_work_hours(now: datetime, hours: WorkHours) -> bool:
    local = now.astimezone(hours.tz) if hours.tz else now.astimezone()
    minute = local.hour * 60 + local.minute
    return local.weekday() in hours.days and hours.start <= minute < hours.end


def last_activity(shipped: dict) -> datetime | None:
    stamps = [parse(shipped.get(key)) for key in ("activity_at", "answered_at", "since", "shipped_at")]
    stamps = [at for at in stamps if at]
    return max(stamps) if stamps else None


def open_told(shipped: dict) -> bool:
    """Items the house was told that his Ship has not answered yet; never his own send-back,
    which no Ship answers (c-663). Every other kind counts as it always did, the rebase item
    among them: this card changes no cadence but his own item's."""
    posted = shipped.get("posted") or {}
    return any(item.get("handle") not in posted for item in shipped.get("told") or []
               if item.get("kind") != HIS_KIND)


def poll_every(now: datetime, shipped: dict, hours: WorkHours) -> timedelta:
    """The cadence above: waiting items first, whatever the hour, then open told items or a
    pull request that moved in the last hour, then work hours, then night."""
    if shipped.get("pending"):
        return WAITING
    moved = last_activity(shipped)
    if open_told(shipped) or (moved is not None and now - moved <= RECENT):
        return FAST
    return NORMAL if in_work_hours(now, hours) else SLOW


def poll_due(now: datetime, last_polled: datetime | None, shipped: dict, hours: WorkHours) -> bool:
    """Time to look again: never looked at by this process, or the cadence."""
    if last_polled is None:
        return True
    return now - last_polled >= poll_every(now, shipped, hours)


# ----- what is new -----

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:30] or "reviewer"


def comment_item(found: dict, now: datetime, part: dict | None = None, prefix: str = "") -> dict:
    handle = f"{prefix}c{found['id']}"
    return with_repo({"kind": "comment", "handle": handle, "id": found["id"],
                      "author": found.get("author") or "someone", "at": found.get("at") or stamp(now),
                      "path": found.get("path"), "line": found.get("line"), "parent": found.get("parent"),
                      "text": capped(str(found.get("text") or ""), handle)}, part)


def comment_file(handle: str) -> str:
    """The file a comment's whole text is kept in, under the card's `comments/`: the handle
    with anything but a word character, a dot or a dash made a dash."""
    return re.sub(r"[^\w.-]", "-", str(handle)).lstrip(".") + ".md"


def capped(text: str, handle: str) -> str:
    """The text as the card keeps it: whole up to TEXT_MAX, else cut so that it and a marker
    naming the whole text's file fit, never cut without saying so."""
    if len(text) <= TEXT_MAX:
        return text
    mark = "\n" + CUT_MARK.format(name=comment_file(handle))
    return text[:TEXT_MAX - len(mark)].rstrip() + mark


def whole_texts(sight: dict) -> dict:
    """Every comment on every pull request of a sight, by its file name under `comments/`:
    a header (who, when, where, what it answers) and the text exactly as the host gave it."""
    out = {}
    for part, _primary, prefix in labelled_parts(sight):
        for found in part.get("comments") or []:
            handle = f"{prefix}c{found['id']}"
            where = found.get("path") or ""
            if where and found.get("line"):
                where = f"{where}:{found['line']}"
            head = [f"{found.get('author') or 'someone'} at {found.get('at') or 'an unknown time'}",
                    f"on `{where}`" if where else "", f"replying to {found['parent']}" if found.get("parent") else "",
                    f"({part['repo']})" if part.get("repo") else ""]
            out[comment_file(handle)] = (f"# {handle}\n\n{' '.join(w for w in head if w)}\n\n"
                                         f"{str(found.get('text') or '')}\n")
    return out


def with_repo(item: dict, part: dict | None) -> dict:
    """An item from a sight that names its repo carries it, so its reply finds its pull request."""
    if part and part.get("repo"):
        item["repo"] = part["repo"]
    return item


# ----- one pull request or several (SH-10) -----

def parts_of(sight: dict) -> list[dict]:
    """The pull requests a sight is about: its `prs` when the card has more than one, else
    the sight itself, which is one pull request's."""
    prs = sight.get("prs")
    if isinstance(prs, list) and prs:
        return [part for part in prs if isinstance(part, dict)]
    return [sight]


def primary_index(parts: list[dict]) -> int:
    """The card's primary pull request: the one the adapter marks, else the first."""
    return next((index for index, part in enumerate(parts) if part.get("primary")), 0)


def prefix_of(part: dict, primary: bool) -> str:
    """What a handle from this pull request starts with: nothing for the primary (so a
    one-pull-request card's handles are what they always were), `<repo>.` for another."""
    return "" if primary else f"{part.get('repo') or 'pr'}."


def labelled_parts(sight: dict) -> list[tuple[dict, bool, str]]:
    """Each pull request of a sight with whether it is the primary and its handles' prefix:
    the one rule `fold` and `whole_texts` both name items by."""
    parts = parts_of(sight)
    main = primary_index(parts)
    return [(part, index == main, prefix_of(part, index == main or len(parts) == 1))
            for index, part in enumerate(parts)]


def combined_state(parts: list[dict]) -> str:
    """Declined when ANY was (his gate), merged only when ALL were, else open."""
    states = [part.get("state") or "open" for part in parts]
    if "declined" in states:
        return "declined"
    return "merged" if all(state == "merged" for state in states) else "open"


def before(found: dict, cutoff: datetime | None, key: str = "at") -> bool:
    """Was this already there when the card entered shipping? With no cutoff, or no time
    on the thing, yes (the old baseline); else only when it is no later than the cutoff."""
    at = parse(found.get(key)) if cutoff else None
    return at is None or at <= cutoff


def edited_after(found: dict, cutoff: datetime | None) -> bool:
    """A comment from before the cutoff whose text was edited after it (c-604 review)."""
    at = parse(found.get("updated")) if cutoff else None
    return at is not None and at > cutoff


def baseline_of(part: dict, cutoff: datetime | None = None) -> dict:
    """What a first look takes as already seen: everything up to `cutoff` (the card's
    `since`, when it entered shipping; c-604: a comment and a failed check ten seconds after
    Approve were baselined away and never told). What came after is left unseen, so the
    same look folds it as new."""
    comments = [c for c in part.get("comments") or [] if before(c, cutoff)]
    edited = edited_of(comments)
    for found in comments:
        if edited_after(found, cutoff):
            edited[str(found["id"])] = str(found.get("at") or "")   # so the fold tells the edit
    ci = part.get("ci") or {}
    old_ci = ci.get("state") != "failed" or before(ci, cutoff)
    # A review is new only by the time its STATE changed (`state_at`), never by `at`, which a
    # host may move whenever the reviewer takes part at all (c-604 review: an old changes
    # requested came back when the reviewer later commented). A sight with no `state_at`
    # has its reviews baselined as before.
    return {"comments": sorted(c["id"] for c in comments), "edited": edited,
            "reviews": {r["author"]: r["state"] for r in part.get("reviews") or []
                        if before(r, cutoff, "state_at")},
            "ci": ci_key(part) if old_ci else ""}


def seen_of(new: dict, part: dict, primary: bool) -> dict | None:
    """What was already seen on this pull request, or None when it was never looked at: the
    primary's is `seen` (the record's shape before SH-10), each other's `seen_other[repo]`."""
    if primary:
        return new.get("seen")
    return (new.get("seen_other") or {}).get(part.get("repo") or "")


def keep_seen(new: dict, part: dict, primary: bool, seen: dict) -> None:
    if primary:
        new["seen"] = seen
    else:
        new.setdefault("seen_other", {})[part.get("repo") or ""] = seen


def ci_key(sight: dict) -> str:
    ci = sight.get("ci") or {}
    return f"{sight.get('head') or ''}:{ci.get('state') or 'none'}"


def facts(sight: dict, pending: list) -> dict:
    ci = (sight.get("ci") or {}).get("state") or "none"
    return {"state": sight.get("state") or "open", "comments": len(sight.get("comments") or []),
            "approvals": int(sight.get("approvals") or 0), "ci": ci,
            "behind": sight.get("behind"), "waiting": len(pending), "draft": bool(sight.get("draft"))}


CI_WORST = ("failed", "running", "passed", "none")


def facts_of(parts: list[dict], pending: list) -> dict:
    """The chip's facts: one pull request's as they always were; for several, the sums
    (comments, approvals), the worst check, the furthest behind, and each one's own in `prs`."""
    if len(parts) == 1:
        return facts(parts[0], pending)
    each, main = [], primary_index(parts)
    for index, part in enumerate(parts):
        one = facts(part, [])
        one.pop("waiting")
        each.append(dict(one, repo=part.get("repo"), pr=part.get("pr"), url=part.get("url"),
                         **({"primary": True} if index == main else {})))   # whose handles have no prefix
    behind = [one["behind"] for one in each if one["behind"] is not None]
    return {"state": combined_state(parts), "draft": any(one["draft"] for one in each),
            "comments": sum(one["comments"] for one in each),
            "approvals": sum(one["approvals"] for one in each),
            "ci": next(word for word in CI_WORST if word == "none" or any(o["ci"] == word for o in each)),
            "behind": max(behind) if behind else None, "waiting": len(pending), "prs": each}


def fold(shipped: dict, sight: dict, now: datetime) -> tuple[dict, list[str]]:
    """The record after this look, and the events it carries (`merged`, `declined`).

    A pull request never looked at before is baselined: what is already there is seen and
    nothing is flagged (on a card's first look, every one of its pull requests, and there
    only what is no later than the record's `since`: what came after it is folded as new
    in the same look, c-604). After
    that, per pull request: every comment by someone else not seen yet joins the batch, a
    review whose state changed is weighed (`fold_reviews`), and a check that failed on the
    head is one item until it passes. The batch is one across all of them."""
    parts = parts_of(sight)
    state = combined_state(parts)
    events = [state] if state in ("merged", "declined") else []
    new = copy.deepcopy(shipped)
    new.setdefault("pending", [])
    first = "seen" not in shipped
    cutoff = parse(shipped.get("since")) if first else None
    for part, primary, prefix in labelled_parts(sight):
        seen = None if first else seen_of(new, part, primary)
        if seen is None:
            seen = baseline_of(part, cutoff)
            keep_seen(new, part, primary, seen)
            if cutoff is None:
                continue
        fold_comments(new, seen, part, now, prefix)
        fold_reviews(new, seen, part, now, prefix)
        fold_ci(new, seen, part, now, prefix)
    new["facts"] = facts_of(parts, new["pending"])
    base = parts[primary_index(parts)].get("base")
    if base:
        new["base"] = base
    return new, events


def moved(new: dict, at: datetime) -> None:
    current = parse(new.get("activity_at"))
    if current is None or at > current:
        new["activity_at"] = stamp(at)


def edited_of(comments: list[dict]) -> dict:
    """`{id: updated}` for every comment the host gives an edit time for."""
    return {str(c["id"]): str(c["updated"]) for c in comments if c.get("updated")}


def fold_comments(new: dict, seen_now: dict, sight: dict, now: datetime, prefix: str = "") -> None:
    """A comment not seen yet joins the batch; so does one seen before whose EDIT time moved
    (c-600 review: the reviewer changed what he asks, so the house is told again, under the
    same handle, which takes its row back to unanswered). A record from before edit times
    were kept just starts keeping them, flagging nothing."""
    seen = set(seen_now.get("comments") or [])
    known = "edited" in seen_now
    edited = dict(seen_now.get("edited") or {})
    for found in sight.get("comments") or []:
        key, updated = str(found["id"]), str(found.get("updated") or "")
        was = edited.get(key)
        if updated:
            edited[key] = updated
        if found["id"] in seen and not (known and was and updated and updated != was):
            continue
        again = found["id"] in seen
        seen.add(found["id"])
        item = comment_item(found, now, sight, prefix)
        if again:
            item["edited"] = True
            item["at"] = updated or stamp(now)
            new["pending"] = [i for i in new["pending"] if i.get("handle") != item["handle"]]
        new["pending"].append(item)
        at = parse(item["at"]) or now
        first, last = parse(new.get("first_at")), parse(new.get("last_at"))
        new["first_at"] = stamp(at if first is None or at < first else first)
        new["last_at"] = stamp(at if last is None or at > last else last)
        moved(new, at)
    seen_now["comments"] = sorted(seen)
    seen_now["edited"] = edited


def fold_reviews(new: dict, seen_now: dict, sight: dict, now: datetime, prefix: str = "") -> None:
    """A review whose state changed since the last look. Changes requested is an item and
    goes at once; an approval goes at once only when the same reviewer has comments waiting
    (an approval with comments), and is otherwise good news for the chip, not work."""
    before = seen_now.get("reviews") or {}
    current = {r["author"]: r["state"] for r in sight.get("reviews") or []}
    where = f" on {sight['repo']}" if prefix and sight.get("repo") else ""
    for review in sight.get("reviews") or []:
        who, state = review["author"], review["state"]
        if before.get(who) == state:
            continue
        at = parse(review.get("at")) or now
        moved(new, at)
        handle = f"{prefix}review-{slug(who)}"
        if state == "changes_requested":
            new["pending"] = [i for i in new["pending"] if i.get("handle") != handle]
            new["pending"].append(with_repo({"kind": "review", "handle": handle, "author": who,
                                             "state": state, "at": stamp(at)}, sight))
            new["urgent"] = f"{who} asked for changes{where}"
        elif state == "approved" and any(i.get("kind") == "comment" and i.get("author") == who
                                         and str(i.get("handle") or "").startswith(prefix)
                                         for i in new["pending"]):
            new["urgent"] = f"{who} approved with comments{where}"
    seen_now["reviews"] = current


def fold_ci(new: dict, seen_now: dict, sight: dict, now: datetime, prefix: str = "") -> None:
    """One item for a failed check on the head, timed from the host's own time for it (as a
    comment is), else from when it was noticed (c-605: the quiet timer started at the
    drain's first look, minutes after the check failed); a later look that finds the checks
    passing or running again takes it back."""
    key, ci = ci_key(sight), sight.get("ci") or {}
    state, handle = ci.get("state") or "none", f"{prefix}ci"
    waiting = [i for i in new["pending"] if i.get("handle") == handle]
    if state == "failed" and seen_now.get("ci") != key:
        at = min(parse(ci.get("at")) or now, now)      # a host clock ahead never waits longer
        new["pending"] = [i for i in new["pending"] if i.get("handle") != handle]
        new["pending"].append(with_repo({"kind": "ci", "handle": handle, "state": state,
                                         "name": ci.get("name"), "url": ci.get("url"),
                                         "at": stamp(at)}, sight))
        new["ci_at"] = stamp(at)
        moved(new, at)
    elif state != "failed" and waiting:
        new["pending"] = [i for i in new["pending"] if i.get("handle") != handle]
        if not any(i.get("kind") == "ci" for i in new["pending"]):
            new.pop("ci_at", None)
    if state != "failed":
        forget_untold(new, handle)
    seen_now["ci"] = key


def forget_untold(new: dict, handle: str) -> None:
    """A check that passes or runs again is taken back from the untold items too (c-655)."""
    kept = [i for i in new.get(UNTOLD) or [] if i.get("handle") != handle]
    if len(kept) != len(new.get(UNTOLD) or []):
        new[UNTOLD] = kept
        if not kept:
            del new[UNTOLD]


# ----- when it goes -----

def due(shipped: dict, now: datetime) -> str | None:
    """Why the waiting items go now, or None: they wait, or nothing waits."""
    pending = shipped.get("pending") or []
    if not pending:
        return None
    if shipped.get("urgent"):
        return str(shipped["urgent"])
    his = sum(1 for item in pending if item.get("kind") == HIS_KIND)
    if his:
        # his own ask never waits on a quiet window, whatever else is in the batch (c-663)
        return HIS_DUE.format(n=his, items="item" if his == 1 else "items")
    quiet = [at for at in (parse(shipped.get("last_at")), parse(shipped.get("ci_at"))) if at]
    first = [at for at in (parse(shipped.get("first_at")), parse(shipped.get("ci_at"))) if at]
    if quiet and now - max(quiet) >= QUIET:
        return "nothing new for 5 minutes"
    if first and now - min(first) >= CAP:
        return "30 minutes since the first waiting item"
    return None


def take_batch(shipped: dict, now: datetime) -> tuple[list[dict], dict]:
    """The waiting items as the next batch, and the record with it told: `round` counted
    on, each item added to `told` with its batch number (a handle told again, a check that
    failed again, replaces its row), the wait and its timers cleared."""
    new = copy.deepcopy(shipped)
    items = new.pop("pending", None) or []
    for timer in TIMERS:
        new.pop(timer, None)
    new["pending"] = []
    new["round"] = int(new.get("round") or 0) + 1
    fresh = {item.get("handle") for item in items}
    told = [item for item in new.get("told") or [] if item.get("handle") not in fresh]
    new["told"] = told + [dict(item, batch=new["round"], told_at=stamp(now)) for item in items]
    new["round_at"] = stamp(now)
    posted = dict(new.get("posted") or {})
    for handle in fresh:
        posted.pop(handle, None)       # a newer comment under the same handle is unanswered
    new["posted"] = posted
    if isinstance(new.get("facts"), dict):
        new["facts"]["waiting"] = 0
    return items, new
