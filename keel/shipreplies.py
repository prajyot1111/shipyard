"""The standing batch of a shipping card (c-600): one row per item the house was told, with
its verdict, and what his Ship posts.

A work card stays at `shipping` from his Approve to the merge, and its build house lives on.
The drain tells the house each batch of review activity (`keel/shipping.py`); the house
judges every item and records ONE VERDICT per item with `kb verdict`, a `verdict` event on
the card (`Board.verdict`): valid, not valid or deferred, a one-line summary of what the
reviewer asks, the reasoning, and the action, a code change (the commits, each with its diff,
read by `kb` in the house's own clone) and/or the exact words of a reply. A later verdict for
the same handle replaces the earlier one. ONE STORE: the rows are derived from the told items
(`options.shipping.told`), the verdict events and his marks, never kept anywhere else.

His marks on a row are `kb mark` with `doc: shipping`, `block: replies`, `row: <handle>`, and
a choice of post, edit (his words ride in the mark) or drop (`keel/planstate.py`). A row he
never marked posts its reply when it has one. Ship (`kb ship`, `Board.ship`) hands the
adapter every kept reply not yet posted with those same words; what it posted is kept as
`options.shipping.posted` ({handle: digest of the words}), so a second Ship never says
anything twice (and the adapter checks the host as well).

Two kinds of item answer no reviewer, so nothing is ever posted for either
(`shipwatch.UNPOSTED_KINDS`): the rebase item (c-651) and his own send-back at shipping
(`his`, c-663, `keel/shipsendback.py`). Such a row carries no words for Ship, takes no post
and no edit, and is counted in no "replies to post"; his own is marked `his` on its row,
and a reply on its verdict is the house's answer to him, shown there and sent nowhere.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from keel import shipwatch, terms
from keel.planstate import EDIT, state_of
# c-651: the item asking the house to merge its base in; nothing is ever posted for it, so
# its row takes no reply, no post and no edit
from keel.shipreoffer import REBASE_KIND

VERDICTS = ("valid", "not-valid", "deferred", "prepared")
# r-55 (c-723): a fix the house prepared that waits on the owner's yes (c-240: a branch
# rebuilt on a new base, which replaces published commits). Its why is the question; it
# carries no reply, may name the prepared commits, and puts the card in needs you until the
# owner sends back (the answer, told to the house as its next item) or a newer verdict on
# the item replaces it (`waiting_on_owner`).
PREPARED = "prepared"
CHOICES = ("post", EDIT, "drop")
BLOCK = "replies"
DOC = "shipping"
TEXT_MAX = 4000
SUMMARY_MAX = 300
DIFF_MAX = 12000
COMMITS_MAX = 8
SHA = re.compile(r"^[0-9a-f]{7,40}$")
GIT_SECONDS = 30


class VerdictRefused(ValueError):
    """A verdict that cannot be recorded as it stands; the message says why."""


def shipping_of(card: dict) -> dict:
    return dict((card.get("options") or {}).get("shipping") or {})


def told_handles(card: dict) -> list[str]:
    return [str(item.get("handle")) for item in shipping_of(card).get("told") or []]


def told_kind(card: dict, handle: str) -> str | None:
    return next((item.get("kind") for item in shipping_of(card).get("told") or []
                 if str(item.get("handle")) == handle), None)


# ----- the house's side: `kb verdict` -----

def gather(args, roots: list[Path]) -> dict:
    """The verdict's data from `kb verdict`'s flags, read HERE (the house's machine): the
    reply file's words and each commit's diff from whichever of the card's worktrees has
    it. `--data` (already gathered, the deck's `kb` over HTTP) is taken as it is."""
    if getattr(args, "data", None):
        try:
            return json.loads(args.data)
        except ValueError as error:
            raise VerdictRefused(f"--data is not JSON: {error}") from None
    reply = args.reply
    if args.reply_file:
        try:
            reply = Path(args.reply_file).expanduser().read_text(errors="replace")
        except OSError as error:
            raise VerdictRefused(f"the reply file cannot be read: {error}") from None
    commits = [{"sha": sha, "diff": commit_diff(sha, roots)} for sha in args.commit or []]
    return {"handle": args.handle, "verdict": args.verdict, "summary": args.summary or "",
            "why": args.why or "", "severity": args.severity or "", "reply": reply or "",
            "commits": commits}


def commit_diff(sha: str, roots: list[Path]) -> str:
    """`git show --stat --patch` of one commit from the first worktree that has it, cut."""
    if not SHA.match(str(sha)):
        raise VerdictRefused(f"{sha!r} is not a commit sha")
    for root in roots:
        try:
            shown = subprocess.run(["git", "-C", str(root), "show", "--stat", "--patch",
                                    "--format=%h %s", str(sha)], capture_output=True, text=True,
                                   timeout=GIT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            continue
        if shown.returncode == 0:
            text = shown.stdout
            return text if len(text) <= DIFF_MAX else text[:DIFF_MAX] + f"\n[cut at {DIFF_MAX} characters]\n"
    raise VerdictRefused(f"no worktree of this card has commit {sha}: commit it first, then record it")


def check(data: dict, card: dict, t=None) -> dict:
    """The one shape a verdict may have, against the card; VerdictRefused says what is wrong."""
    if not isinstance(data, dict):
        raise VerdictRefused("a verdict is an object")
    handle = str(data.get("handle") or "").strip()
    if handle not in told_handles(card):
        raise VerdictRefused(f"{handle or 'no handle'} is not an item you were told on {card['id']} "
                             f"(told: {', '.join(told_handles(card)) or 'none yet'})")
    verdict = data.get("verdict")
    if verdict not in VERDICTS:
        raise VerdictRefused(f"a verdict is one of {', '.join(VERDICTS)}")
    why = short(data.get("why"), TEXT_MAX, "the reasoning")
    if not why:
        raise VerdictRefused("a verdict says why (--why): the reasoning, checked against the code")
    reply = short(data.get("reply"), TEXT_MAX, "the reply")
    commits = [one for one in data.get("commits") or [] if isinstance(one, dict)]
    if len(commits) > COMMITS_MAX:
        raise VerdictRefused(f"at most {COMMITS_MAX} commits per verdict")
    if verdict == PREPARED:
        # c-723 review r1.F6: the owner's own send-back is the owner asking, so a fix for it
        # never waits on the owner again. The rebase item may: c-240's was a rebuild on a new
        # base that replaced pushed commits, which is the owner's call.
        if told_kind(card, handle) == shipwatch.HIS_KIND:
            raise VerdictRefused(f"{handle} is the user's own send-back: do it, or say plainly why not "
                                 "(valid, not-valid or deferred); it is never prepared")
        return prepared_verdict(data, handle, why, reply, commits)
    if commits and verdict != "valid":
        raise VerdictRefused("a code change answers only a valid comment; a not-valid or deferred "
                             "one gets a reply")
    if told_kind(card, handle) == REBASE_KIND:
        return rebase_verdict(data, handle, verdict, why, commits)
    if told_kind(card, handle) == shipwatch.HIS_KIND:
        return his_verdict(data, handle, verdict, why, reply, commits)
    if verdict == "valid" and not commits:
        # the method's rule (adapters' comments.md, c-600 review): valid means changed now
        raise VerdictRefused(terms.say(t, "a valid item gets a code change (--commit); one you will not "
                                          "change in this {change} is deferred, with a reply saying why"))
    if verdict != "valid" and not reply:
        raise VerdictRefused(f"a {verdict} comment gets a reply (--reply-file): the words to post")
    return shaped(data, handle, verdict, why, reply, commits)


def rebase_verdict(data: dict, handle: str, verdict: str, why: str, commits: list[dict]) -> dict:
    """c-651: the branch brought up to its base answers no reviewer, so nothing is ever posted
    for it: valid with the merge commit, or deferred (with the why) when the house cannot
    finish it, and never a reply."""
    if str(data.get("reply") or "").strip() or verdict == "not-valid":
        raise VerdictRefused("the rebase item gets no reply: --verdict valid --commit <the merge "
                             "commit>, or --verdict deferred --why \"<what stops it>\"")
    if verdict == "valid" and not commits:
        raise VerdictRefused("a valid rebase item names the merge commit (--commit)")
    return shaped(data, handle, verdict, why, "", commits)


def his_verdict(data: dict, handle: str, verdict: str, why: str, reply: str, commits: list[dict]) -> dict:
    """c-663: his own send-back is the owner asking, not a reviewer. Valid names the commits
    that did it; not-valid or deferred says plainly why not in its why. A reply is optional
    and is the house's answer to him: it is shown on his row and never posted."""
    if verdict == "valid" and not commits:
        raise VerdictRefused("a valid item of the user's names the commits that did it (--commit); one you "
                             "will not do is not-valid or deferred, with the why saying plainly why not")
    return shaped(data, handle, verdict, why, reply, commits)


def prepared_verdict(data: dict, handle: str, why: str, reply: str, commits: list[dict]) -> dict:
    """r-55 (c-723): a fix prepared and waiting on the owner's yes. The why is the question
    the owner answers (what is prepared, where, and what you ask); nothing is posted for it,
    so it takes no reply. The commits it names are the prepared ones, shown for a look."""
    if reply:
        raise VerdictRefused("a prepared item gets no reply: nothing is posted while it waits on the user. "
                             "Its --why says what you prepared and asks the user; record the item again "
                             "once they answer")
    return shaped(data, handle, PREPARED, why, "", commits)


def waiting_on_owner(card: dict, events: list[dict]) -> list[dict]:
    """`[{handle, why, at}]`: the told items whose newest verdict is `prepared` and that the
    owner has not answered since, oldest first. A send-back answers only the items it names
    (`answers` on its note, a line led by the handle, as the deck's Answer leads it;
    `shipsendback.answers`, c-723 review r1.F5), and only a verdict recorded before it."""
    answered: dict[str, int] = {}
    for event in events:
        data = event.get("data") if event.get("kind") == "note" else None
        if isinstance(data, dict) and data.get("sendback"):
            for handle in data.get("answers") or []:
                answered[str(handle)] = max(answered.get(str(handle), 0), int(event.get("id") or 0))
    return [{"handle": row["handle"], "why": row["verdict"].get("why") or "", "at": row["verdict"].get("at")}
            for row in rows(card, events)
            if (row["verdict"] or {}).get("verdict") == PREPARED
            and int(row["verdict"].get("event") or 0) > answered.get(row["handle"], 0)]


def waiting_on(conn, card_id: str, options: dict) -> list[dict]:
    """`waiting_on_owner` for a card read: only the verdicts' handles, kinds, whys and times,
    and the send-back notes' ids, never a verdict's diffs (every read of a shipping card
    derives it)."""
    found = conn.execute(
        "SELECT id, kind, at, json_extract(data, '$.handle'), json_extract(data, '$.verdict'), "
        "json_extract(data, '$.why'), json_extract(data, '$.answers') FROM events WHERE card = ? AND "
        "(kind = 'verdict' OR (kind = 'note' AND json_extract(data, '$.sendback') IS NOT NULL)) ORDER BY id",
        (card_id,))
    events = [{"id": id_, "kind": kind, "at": at,
               "data": ({"handle": handle, "verdict": verdict, "why": why} if kind == "verdict"
                        else {"sendback": True, "answers": json.loads(named or "[]")})}
              for id_, kind, at, handle, verdict, why, named in found]
    return waiting_on_owner({"options": options}, events)


def shaped(data: dict, handle: str, verdict: str, why: str, reply: str, commits: list[dict]) -> dict:
    return {"handle": handle, "verdict": verdict, "why": why, "reply": reply,
            "summary": short(data.get("summary"), SUMMARY_MAX, "the summary"),
            "severity": short(data.get("severity"), 40, "the severity"),
            "commits": [{"sha": str(one.get("sha") or "")[:40],
                         "diff": str(one.get("diff") or "")[:DIFF_MAX + 100]} for one in commits]}


def short(value, cap: int, what: str) -> str:
    text = str(value or "").strip()
    if len(text) > cap:
        raise VerdictRefused(f"{what} is longer than {cap} characters")
    return text


# ----- the rows, as the deck draws them and Ship reads them -----

def verdicts_of(events: list[dict]) -> dict:
    """The newest verdict per handle, with when it was recorded."""
    out = {}
    for event in events:
        if event.get("kind") != "verdict":
            continue
        data = event.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict) and data.get("handle"):
            out[str(data["handle"])] = dict(data, at=event.get("at"), event=event.get("id"))
    return out


def digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]


def since(events: list[dict], told_at: str | None) -> list[dict]:
    """The events recorded at or after an item was told. A handle is reused (`ci`, a
    reviewer's `review-<who>`, a comment edited on the host): the verdict and his marks from
    the item it replaced belong to that one, never this one (c-600 review)."""
    start = when(told_at)
    if start is None:
        return events
    return [event for event in events if (when(event.get("at")) or start) >= start]


def when(stamp) -> datetime | None:
    """An ISO stamp as an aware instant: the drain's `told_at` and the board's event times may
    carry different offsets (the Mac's and the box's clocks), so they are never compared as text."""
    try:
        at = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else at.astimezone()


def unjudged(card: dict, events: list[dict], batch: int | None = None,
             but: int | None = None) -> list[str]:
    """The handles the house was told (in `batch`, or in any) that have no verdict since they
    were told (c-654): told is not judged. `kb ship <id> reoffer` offers these again, and a
    re-offered batch whose turn ended with any is his, never "answered". `but`: a batch left
    out, the one its house is still on (`shipreoffer.held`)."""
    return [str(item.get("handle")) for item in batch_items(card, batch)
            if (but is None or item.get("batch") != but)
            and str(item.get("handle")) not in verdicts_of(since(events, item.get("told_at")))]


def batch_items(card: dict, batch: int | None = None) -> list[dict]:
    """The told items of one batch, or every told item."""
    return [item for item in shipping_of(card).get("told") or []
            if batch is None or item.get("batch") == batch]


def rows(card: dict, events: list[dict]) -> list[dict]:
    """Every told item, oldest batch first, with its verdict (or None while the house
    judges it), his choice and words, the words Ship would post, and whether they are posted.

    Only what was recorded since THIS item was told counts (`since`). A reply once posted is
    posted: his edit after it is shown but never sent as a second reply (`Board.mark`
    refuses one, and `kept` leaves the row out)."""
    shipped = shipping_of(card)
    posted = shipped.get("posted") or {}
    out = []
    for item in shipped.get("told") or []:
        handle = str(item.get("handle"))
        mine = since(events, item.get("told_at"))
        verdict = verdicts_of(mine).get(handle)
        marks = state_of(mine, DOC)
        pick = marks["rows"].get(BLOCK, {}).get(handle)
        edited = marks["edits"].get(BLOCK, {}).get(handle) or ""
        reply = (verdict or {}).get("reply") or ""
        choice = pick or ("post" if reply else None)
        words = edited if choice == EDIT else (reply if choice == "post" else "")
        row = {"handle": handle, "item": item, "verdict": verdict, "choice": choice,
               "edited": edited, "words": words,
               "posted": handle in posted, "posted_before": handle in posted}
        if item.get("kind") == shipwatch.HIS_KIND:
            # his own send-back (c-663): its answer is shown to him here and goes nowhere
            row.update(his=True, choice=None, edited="", words="", posted=False, posted_before=False)
        out.append(row)
    return out


def kept(card: dict, events: list[dict]) -> list[dict]:
    """The replies his Ship posts now: every row kept (post, or edit with his words) that
    has not been posted, in the order the items were told."""
    return [{"handle": row["handle"], "text": row["words"]} for row in rows(card, events)
            if postable(row)]


def postable(row: dict) -> bool:
    """Words kept and not posted yet, on a row that answers a reviewer (never the rebase item
    and never his own send-back, `shipwatch.UNPOSTED_KINDS`)."""
    return (bool(row["words"]) and not row["posted"]
            and row["item"].get("kind") not in shipwatch.UNPOSTED_KINDS)


def refuse_after_post(card: dict, data: dict, t=None) -> str | None:
    """His mark on a reply already posted: a second reply is never sent, so an edit or a
    post there is refused, with where to change it (the host). A drop is harmless. A post
    or an edit on the rebase row is refused too: it answers no reviewer (c-651), and so is
    one on a row of his own send-back (c-663)."""
    if data.get("doc") != DOC or data.get("block") != BLOCK or data.get("choice") == "drop":
        return None
    handle = str(data.get("row") or "")
    if handle and told_kind(card, handle) == REBASE_KIND:
        return "the rebase item answers no reviewer, so nothing is posted for it: drop is its only mark"
    if handle and told_kind(card, handle) == shipwatch.HIS_KIND:
        return f"{handle} is the user's own send-back: its answer is shown on the card and nothing is posted for it"
    if handle and handle in (shipping_of(card).get("posted") or {}):
        return (f"the reply to {handle} is already posted on the {(t or terms.BASE)['change']}; a second one is "
                f"never sent. Change it there, or Talk to the house")
    return None


def ship_answer(card: dict, events: list[dict]) -> dict:
    """What Ship hands the adapter's `publish --answer` on stdin: the replies, and `lease`,
    the head Keel last saw each branch at (the publish, then each Ship's push; c-600 review),
    which the push leases against so a colleague's push since is never overwritten."""
    return {"ship": True, "replies": kept(card, events),
            "lease": dict(shipping_of(card).get("heads") or {})}


def summary(card: dict, events: list[dict], found: list[dict] | None = None) -> dict:
    """The counts the pane and Ship's confirm say: rows judged, replies kept and not posted,
    commits the house recorded, and the worktrees' facts as last read. `shipped_at` is his
    last Ship's stamp, by which the deck knows these counts are from after it (c-660).
    `found`: the rows, when the caller has read them already (the comments page)."""
    found = rows(card, events) if found is None else found
    shipped = shipping_of(card)
    return {"told": len(found), "judging": sum(1 for row in found if not row["verdict"]),
            "to_post": sum(1 for row in found if postable(row)),
            "local": shipped.get("local") or {}, "draft": bool((shipped.get("facts") or {}).get("draft")),
            "shipped_at": shipped.get("shipped_at")}


def ship_line(answer: dict, before: dict | None = None) -> str:
    """One sentence for the card's record from the adapter's answer to a Ship. `before` is
    the branch heads the card knew before this Ship (`shipping.heads`): a repo the adapter
    "pushed" at the head it already had moved nothing, so it is not said (c-605: the toast
    read "pushed web 01282a6" when the confirm had said "nothing new")."""
    pushed = answer.get("pushed") or {}
    before = before or {}
    heads = ", ".join(f"{repo} {str(sha)[:10]}" for repo, sha in pushed.items()
                      if str(sha) != str(before.get(repo) or "")) if isinstance(pushed, dict) else str(pushed)[:10]
    posted = [str(one) for one in answer.get("posted") or []]
    parts = [f"pushed {heads}" if heads else "nothing new to push"]
    skipped = [str(repo) for repo in answer.get("skipped") or []]
    if skipped:
        # the adapter's word (c-653): that repo's branch on the remote already holds more
        parts.append(f"nothing pushed from {', '.join(skipped)} (its branch on the remote is ahead)")
    if answer.get("ready"):
        parts.append("marked ready")
    parts.append(f"posted {len(posted)} {'reply' if len(posted) == 1 else 'replies'}"
                 + (f" ({', '.join(posted)})" if posted else ""))
    return "shipped: " + ", ".join(parts)
