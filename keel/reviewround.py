"""What his Approve of a review card posts (lane RC, RC-4), worked out where the card's
record is.

A review card's outcome is the review kind (`keel/planreview.py`): one `finding` block per
finding (lane FC), each at a `path:line` with its drafted comment and its choice of post,
edit or drop, and a `decision verdict`; an outcome written before lane FC, in the old batch
with `copy comment` blocks, is read the same way (`planreview.items`). His picks are marks
on the card (`keel/planstate.py`); a finding or a verdict he left takes the house's
recommendation, as every Approve does.
`answer_for` turns the two into the ANSWER `adapters.publish` hands the adapter's `publish
--answer` on stdin, so posting takes the door's path and lock like any publish:

    {"review": {"round", "head", "comments": [{"row", "path", "line", "text", "severity"}],
                "summary", "verdict": "comment" | "changes" | "approve", "severity",
                "ledger": [{"id", "path", "line", "choice", "claim"}]}}

- **comments**: each row at post (the house's draft) or at edit (HIS words, RC-3), at the
  row's `path:line`; a row at drop is not posted.
- **summary**: the outcome's one paragraph (what the change does) and the counts.
- **verdict**: his pick of comment only (nothing posted), request changes or approve.
- **ledger**: every row with what he did with it, so a re-review never raises again what he
  posted or dropped on lines that did not change (`keel/review/ledger.py`, C31).

Refused, before anything is posted: an edit left empty, a choice that is not post, edit or
drop, a kept row with no words or no line, and a verdict that is not one of the three.

A FEATURE card (lane GRP, `options.review_members`) answers the same shape plus `members`:
one entry per pull request, {"member", "repo", "pr", "head", "comments", "verdict"}, its
comments the kept rows that name it and its verdict its own `decision
verdict-<repo>-<number>` (`planreview.verdict_id`). The summary names every member's tally
and is posted on each; `verdict` is the strongest of theirs (request changes, then comment
only, then approve), what the card says once posted. A row naming no member, or a member
with no verdict, refuses the Approve before anything is posted.
"""

from __future__ import annotations

from keel import planformat, planreview, planstate
from keel.board import Refused, open_board
from keel.config import Config
from keel.planinline import plain
from keel.review import findings as review_findings, gate as review_gate, ledger as review_ledger, twins as review_twins

KEPT = ("post", "edit")
SEVERITY_ORDER = review_findings.SEVERITIES


class ReviewRefused(Refused):
    """His picks on a review cannot be posted as they stand; the message says why."""


def record_of(cfg: Config, card: dict) -> str:
    path = cfg.card_dir(card["id"]) / "context.md"
    return path.read_text(errors="replace") if path.is_file() else ""


def answer_for(cfg: Config, card: dict) -> dict | None:
    """The answer `publish` is handed for a review card at its gate, else None."""
    if card.get("stage") != "review" or not review_gate.is_review_card(card):
        return None
    doc = planformat.parse(record_of(cfg, card), "context.md")
    if doc["kind"] != "review":
        raise ReviewRefused(f"{card['id']}'s outcome is not a review (`kind: review`); send it back")
    board = open_board(cfg)
    try:
        events = board.events(card["id"], last=0)
    finally:
        board.close()
    state = planstate.state_of(events, "outcome")
    severities = severity_by_row(cfg.card_dir(card["id"]))
    options = card.get("options") or {}
    members = options.get("review_members") or []
    paired = review_twins.followed(cfg.card_dir(card["id"]))
    left = sorted(f"{twin} (twin of {primary})" for twin, primary in paired.items()
                  if primary not in {m["label"] for m in members})
    if left:
        raise ReviewRefused(f"the member a twin follows is no longer on the card: {', '.join(left)}; "
                            f"send the review back so it is reviewed as it stands")
    comments, ledger = picked(doc, state, severities, [m["label"] for m in members if m["label"] not in paired])
    if members:
        return {"review": feature_answer(doc, state, options, members, comments, ledger, paired)}
    return {"review": {"round": int(options.get("review_round") or 1), "head": options.get("review_head"),
                       "comments": comments, "summary": summary(doc, comments, options.get("review_head")),
                       "verdict": verdict(doc, state), "severity": highest(comments), "ledger": ledger}}


def highest(comments: list[dict]) -> str | None:
    """The highest severity among the comments he kept: what the card says once posted."""
    found = [c.get("severity") for c in comments if c.get("severity") in SEVERITY_ORDER]
    return min(found, key=SEVERITY_ORDER.index) if found else None


def severity_by_row(card_dir) -> dict:
    last = review_ledger.newest_complete(card_dir) or {}
    return {planreview.row_id(one["id"]): one.get("severity") for one in last.get("findings") or []}


def picked(doc: dict, state: dict, severities: dict, members: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """The comments to post, in the outcome's order, and the ledger of every finding; on a
    feature card each names its member. The findings are read in either shape
    (`planreview.items`): one ```finding block each (lane FC), or an outcome already at his
    gate in lane RC's batch with `copy comment` blocks."""
    comments, ledger = [], []
    for one in planreview.items(doc, members):
        block_id, row = one["mark"]
        choice = state.get("rows", {}).get(block_id, {}).get(row) or one["rec"]
        if choice not in planreview.FINDING_CHOICES:
            raise ReviewRefused(f"{one['id']} is at {choice!r}; a finding is post, edit or drop")
        member = member_or_refuse(one, members) if members else None
        ledger.append({"id": one["id"], "path": one["path"], "line": one["line"],
                       "choice": "drop" if choice == "drop" else "post", "claim": one["claim"][:200]})
        if member:
            ledger[-1]["member"] = member
        if choice == "drop":
            continue
        text = edited(state, block_id, row) if choice == "edit" else one["comment"]
        if not text:
            raise ReviewRefused(f"{one['id']} has no words to post; send the review back")
        if one["path"] is None:
            raise ReviewRefused(f"{one['id']} names no line to post at; send the review back")
        comments.append({"row": one["id"], "path": one["path"], "line": one["line"], "text": text,
                         "severity": severities.get(one["id"]) or one["severity"]})
        if member:
            comments[-1]["member"] = member
    return comments, ledger


def member_or_refuse(one: dict, members: list[str]) -> str:
    if one["member"] not in members:
        raise ReviewRefused(f"{one['id']} names no member ({', '.join(members)}); send the review back")
    return one["member"]


VERDICT_ORDER = ("changes", "comment", "approve")


def feature_answer(doc: dict, state: dict, options: dict, members: list[dict], comments: list[dict],
                   ledger: list[dict], paired: dict | None = None) -> dict:
    """A feature card's answer (lane GRP): per member its comments, head and verdict. A
    twin (`keel/review/twins.py`, c-559) was not reviewed: no comment, the verdict of the
    member it follows, and `pointer`, the one comment it gets in place of the summary."""
    heads = options.get("review_heads") or {}
    paired = paired or {}
    per = []
    for member in sorted(members, key=lambda m: m["label"] in paired):
        label = member["label"]
        one = {"member": label, "repo": member.get("repo"), "pr": member.get("pr"),
               "head": heads.get(label) or member.get("head")}
        if label in paired:
            primary = next(p for p in per if p["member"] == paired[label])
            one.update(twin_side(primary, next((m for m in members if m["label"] == paired[label]), {})))
        else:
            one.update(comments=[c for c in comments if c.get("member") == label],
                       verdict=verdict(doc, state, planreview.verdict_id(label), label))
        per.append(one)
    per.sort(key=lambda p: [m["label"] for m in members].index(p["member"]))
    strongest = min((one["verdict"] for one in per), key=VERDICT_ORDER.index)
    return {"round": int(options.get("review_round") or 1), "head": options.get("review_head"),
            "heads": {one["member"]: one["head"] for one in per}, "members": per, "comments": comments,
            "summary": feature_summary(doc, per), "verdict": strongest, "severity": highest(comments),
            "ledger": ledger}


def twin_side(primary: dict, followed: dict) -> dict:
    """A twin's part: no comment, the verdict of the member it follows, and one line
    pointing at that member's review."""
    where = f" ({followed['url']})" if followed.get("url") else ""
    return {"comments": [], "verdict": primary["verdict"], "twin_of": primary["member"],
            "pointer": f"The same change as {primary['member']}{where}, raised into another base: it was "
                       f"reviewed once, there, and its comments are on that one."}


def feature_summary(doc: dict, per: list[dict]) -> str:
    """The one general comment every member gets: what the feature does, then each
    member's tally, so each pull request's author sees the other side's too."""
    said = plain(doc.get("summary") or []).strip()
    lines = [f"{one['member']}: {tally(one['comments'])}, reviewed at {str(one['head'])[:10]}."
             if not one.get("twin_of") else
             f"{one['member']}: the twin of {one['twin_of']} (the same change on another base), reviewed there."
             for one in per]
    body = "Reviewed together as one change:\n" + "\n".join(f"- {line}" for line in lines)
    return f"{said}\n\n{body}" if said else body


def tally(comments: list[dict]) -> str:
    counts = [f"{sum(c.get('severity') == level for c in comments)} {level}"
              for level in SEVERITY_ORDER if any(c.get("severity") == level for c in comments)]
    said = f"{len(comments)} inline comment{'s' if len(comments) != 1 else ''}"
    return said + (f" ({', '.join(counts)})" if counts else "")


def edited(state: dict, block_id: str, row_id: str) -> str:
    text = str(state.get("edits", {}).get(block_id, {}).get(row_id) or "").strip()
    if not text:
        raise ReviewRefused(f"{row_id} is marked edit with no words: type what to post in its field, "
                            f"or pick post or drop; nothing was posted")
    return text


def verdict(doc: dict, state: dict, block_id: str = planreview.VERDICT_ID, label: str | None = None) -> str:
    block = next((b for b in planformat.all_blocks(doc["blocks"])
                  if b["type"] == "decision" and b.get("id") == block_id), None)
    if block is None:
        raise ReviewRefused(f"{label} has no verdict; send it back" if label else "the review has no verdict; send it back")
    mine = state.get("answers", {}).get(block["id"]) or {}
    if mine.get("other"):
        raise ReviewRefused("the verdict is comment only, request changes or approve; pick one")
    chosen = mine.get("option") or block.get("rec")
    if chosen not in planreview.VERDICTS:
        raise ReviewRefused(f"the verdict is at {chosen!r}; it is comment, changes or approve")
    return chosen


def summary(doc: dict, comments: list[dict], head: str | None) -> str:
    """The one general comment: what the change does, then the counts."""
    said = plain(doc.get("summary") or []).strip()
    counts = [f"{sum(c.get('severity') == level for c in comments)} {level}"
              for level in SEVERITY_ORDER if any(c.get("severity") == level for c in comments)]
    tally = f"{len(comments)} inline comment{'s' if len(comments) != 1 else ''}"
    tally += f" ({', '.join(counts)})" if counts else ""
    tail = f"{tally}, reviewed at {str(head)[:10]}." if head else f"{tally}."
    return f"{said}\n\n{tail}" if said else tail
