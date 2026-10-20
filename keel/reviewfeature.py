"""A story's pull requests as ONE review card (lane GRP, GR-1 and GR-4).

The old review scanner reviewed every open pull request of one story together (the story
id in the branch name): the backend and frontend halves of a feature, so a bug that lives
only at the seam between them is seen. The adapter says which story a pull request belongs
to (`group` on each row of `review scan`, its own rule on the branch name); this module
does the rest, in the engine's words:

- **units**: the rows of one group that need him, when there are two or more, are ONE
  feature card keyed `feature:<group>`; a row with no group, or alone in its group, is a
  single card as before. A group whose every member already has a single card that is
  posted at its current head (or closed) files nothing: both halves were reviewed alone
  and there is nothing new to review together.
- **the card**: titled "Review: <group> · <story title>" (the adapter's `review story`,
  else the first member's title), `repo` the members' repos (a cross-repo card),
  `options.review_members` one record per pull request (repo, pr, head, branch, url,
  author, raised), and `options.review_pr` the facts the backlog and the deck read, over
  all of them.
- **members change**: a pull request that joins or leaves updates the card with a note;
  the members' heads together are the card's head (`composite_head`), so a push on any
  member, or a new member, is "new commits since your review" on a posted card.
- **folding** (GR-4): a member's own single card is archived with a note pointing at the
  feature card when nobody is deciding it (at the inbox, held included, or posted: its
  ledger joins the feature's as `options.review_carried`). One under review or at his gate
  is NEVER folded: it gets a note and he decides, and the feature card then waits at the
  inbox even with auto review on.
- **twins** (c-559): the adapter may say a member is the same change as another member of
  its repo, raised on another base (`twin_of`, the other's label, on the scan's row; the
  rule and the base names it reads are the adapter's alone, decision TW-3). A twin stays a member: it is on the card, its head is in
  `composite_head`, so a push on it is still "new commits since your review". But only the
  member it names is reviewed and commented on: prep leaves the twin's diff out
  (`keel/review/twins.py`), the lint wants no finding and no verdict for it and wants the
  orientation to name it with the member it follows, and his Approve gives it one pointer
  comment to that member's review and the same verdict.

Everything is written on the card, and only when it changes. Nothing here posts.
"""

from __future__ import annotations

from keel import reviewwait, terms

FEATURE_PREFIX = "feature:"
MEMBERS_OPTION = "review_members"
GROUP_OPTION = "review_group"
FOLDED_OPTION = "review_folded"
CARRIED_OPTION = "review_carried"
MEMBER_FIELDS = ("key", "repo", "pr", "head", "branch", "base", "url", "author", "title")
BUSY_WORDS = {"assigned": "queued for review", "planning": "being reviewed", "building": "being reviewed",
              "review": "at your gate", "shipping": "shipping"}


def feature_key(group: str) -> str:
    return f"{FEATURE_PREFIX}{group}"


def is_feature(card: dict) -> bool:
    return str((card.get("options") or {}).get("review_key") or "").startswith(FEATURE_PREFIX)


def label_of(row: dict) -> str:
    """A member's name everywhere: its repo and number, `cloud#4150`."""
    return f"{row['repo']}#{int(row['pr'])}"


def member_of(row: dict) -> dict:
    member = {name: row.get(name) for name in MEMBER_FIELDS}
    member.update(label=label_of(row), raised=row.get("created"))
    if row.get("twin_of"):
        member["twin_of"] = str(row["twin_of"])     # only when said: a member without one is unchanged
    return member


def members_of(rows: list[dict]) -> list[dict]:
    """The members in one fixed order (repo, then number), whatever order the host gave."""
    return [member_of(row) for row in sorted(rows, key=lambda r: (str(r["repo"]), int(r["pr"])))]


def composite_head(members: list[dict]) -> str:
    """Every member's head in one string: the card's head, so a push on any member, or a
    member joining or leaving, is a new head."""
    return ",".join(f"{m['label']}@{m.get('head')}" for m in sorted(members, key=lambda m: m["label"]))


def groups(rows: list[dict]) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("group"):
            found.setdefault(str(row["group"]), []).append(row)
    return found


def feature_row(members: list[dict], title: str) -> dict:
    """The facts of the whole feature, in the shape one pull request's facts have, so the
    backlog rule and the deck read a feature card as they read any review card."""
    stamps = [m.get("raised") for m in members if m.get("raised")]
    authors = list(dict.fromkeys(str(m.get("author")) for m in members if m.get("author")))
    return {"author": ", ".join(authors) or None, "created": min(stamps) if stamps else None,
            "url": members[0].get("url"), "head": composite_head(members), "title": title}


def settled(card: dict | None, row: dict) -> bool:
    """A member's single card with nothing left to review: closed, or posted at the head
    the pull request has now."""
    if card is None:
        return False
    options = card.get("options") or {}
    if options.get("review_closed"):
        return True
    posted = options.get("review_posted") or {}
    return card["stage"] == "done" and bool(posted) and posted.get("head") == row.get("head") \
        and not options.get("review_new")


def is_unit(cards: dict, group: str, rows: list[dict]) -> bool:
    """The group is reviewed as a feature: it has a feature card (even down to one member,
    which never gets a single card of its own), or two or more members and a reason."""
    if feature_key(group) in cards:
        return True
    return len(rows) > 1 and wanted(cards, group, rows)


def wanted(cards: dict, group: str, rows: list[dict]) -> bool:
    """A new feature card is worth filing: some member is not settled."""
    return not all(settled(cards.get(row["key"]), row) for row in rows)


# ----- filing -----

def words(ctx) -> terms.Terms:
    """The pass's space's words (c-630); a pass with no config says the defaults."""
    return terms.of(getattr(ctx, "cfg", None), getattr(ctx, "space", None))


def brief_of(group: str, members: list[dict], rows: list[dict], t=None) -> str:
    lines = [f"Review the {terms.say(t, '{changes}')} of {group} together, as one change:"]
    lines += [f"- {m['label']}: {m.get('title') or ''}, by {m.get('author') or 'someone'} ({m.get('url')})"
              for m in members]
    described = [f"{label_of(row)}:\n{str(row.get('description') or '').strip()}"
                 for row in rows if str(row.get("description") or "").strip()]
    return "\n\n".join(["\n".join(lines)] + described)


def story_title(ctx, group: str) -> str | None:
    found = ctx.ask("story", group)
    title = (found or {}).get("title") if isinstance(found, dict) else None
    return str(title).strip() or None if title else None


def file_feature(ctx, group: str, rows: list[dict]) -> str:
    """ONE feature card for the group, then the members' single cards folded into it."""
    members = members_of(rows)
    title = story_title(ctx, group) or members[0].get("title") or group
    facts = ctx.facts(feature_row(members, title), {})
    options = {"kind": "review", "review_key": feature_key(group), "slot": ctx.slot, GROUP_OPTION: group,
               "base": members[0].get("base"), "tracker_mode": "none", MEMBERS_OPTION: members,
               ctx.pr_option: facts}
    repos = list(dict.fromkeys(m["repo"] for m in members))
    card_id = ctx.create(f"Review: {group} · {title}", brief_of(group, members, rows, words(ctx)), ",".join(repos), options)
    undecided = fold(ctx, card_id, group, rows)
    wait = reviewwait.wait_for(ctx, group, repos)
    labels = ", ".join(m["label"] for m in members)
    said = f"feature review of {group} ({labels}), filed by the review fetcher"
    if wait:
        reviewwait.hold(ctx, card_id, wait, said)
    elif ctx.auto and not undecided:
        ctx.board.stage(card_id, "assigned", ctx.actor, note=said + "; auto review is on, so it is assigned")
    else:
        why = "; a member's own review is not folded, so it waits for you" if undecided and ctx.auto else ""
        ctx.board.note(card_id, said + why + "; tap Review to start it", ctx.actor)
    return card_id


# ----- members changing -----

def update_members(ctx, card: dict, rows: list[dict]) -> None:
    """Keep the members current: a join or a leave is noted, a join's single card folded;
    a new head is only a fact here (the fetcher's tend says "new commits")."""
    if card["derived"]["archived"] or (card.get("options") or {}).get("review_closed"):
        return
    before = (card.get("options") or {}).get(MEMBERS_OPTION) or []
    after = members_of(rows)
    if after == before:
        return
    old, new = {m["label"] for m in before}, {m["label"] for m in after}
    fields = {"options": {MEMBERS_OPTION: after}}
    repos = ",".join(dict.fromkeys(m["repo"] for m in after))
    if repos != card.get("repo"):
        fields["repo"] = repos
    ctx.board.set_fields(card["id"], fields, ctx.actor)
    for label in sorted(new - old):
        ctx.board.note(card["id"], f"{label} joined {card['options'].get(GROUP_OPTION)}: it is reviewed "
                                   f"with the others from now on", ctx.actor)
    for label in sorted(old - new):
        ctx.board.note(card["id"], f"{label} left: it no longer needs your review (merged, declined, "
                                   f"approved or you were taken off it)", ctx.actor)
    joined = [row for row in rows if label_of(row) in new - old]
    if joined:
        fold(ctx, card["id"], card["options"].get(GROUP_OPTION), joined)


# ----- folding (GR-4) -----

def fold(ctx, feature_id: str, group: str, rows: list[dict]) -> list[str]:
    """Fold each member's own single card into the feature card; the ids of the ones left
    for him to decide."""
    undecided = []
    for row in rows:
        card = ctx.cards.get(row["key"])
        if card is None or card["id"] == feature_id or card["derived"]["archived"]:
            continue
        options = card.get("options") or {}
        if options.get("review_closed"):
            continue
        if card["stage"] == "inbox" or (card["stage"] == "done" and options.get("review_posted")):
            fold_one(ctx, feature_id, group, card, label_of(row))
        else:
            leave_one(ctx, feature_id, group, card, label_of(row))
            undecided.append(card["id"])
    return undecided


def fold_one(ctx, feature_id: str, group: str, card: dict, label: str) -> None:
    posted = (card.get("options") or {}).get("review_posted")
    if posted:
        carry(ctx, feature_id, label, posted)
    ctx.board.set_fields(card["id"], {"options": {"archived": True, FOLDED_OPTION: feature_id,
                                                  reviewwait.WAIT_OPTION: None}}, ctx.actor)
    ctx.board.note(card["id"], f"folded into {feature_id}, which reviews {group} as one feature"
                               + (": what you posted here goes with it" if posted else ""), ctx.actor)
    ctx.board.note(feature_id, f"{card['id']} ({label}) folded in"
                               + (", with what you posted on it" if posted else ""), ctx.actor)


def carry(ctx, feature_id: str, label: str, posted: dict) -> None:
    """A posted single review's ledger joins the feature's, each line naming its member,
    so the feature review never raises again what he answered there."""
    feature = ctx.board.get(feature_id)
    carried = list((feature.get("options") or {}).get(CARRIED_OPTION) or [])
    carried.append({"member": label, "head": posted.get("head"), "round": posted.get("round"),
                    "ledger": [dict(one, member=label) for one in posted.get("ledger") or []]})
    ctx.board.set_fields(feature_id, {"options": {CARRIED_OPTION: carried}}, ctx.actor)


def leave_one(ctx, feature_id: str, group: str, card: dict, label: str) -> None:
    where = BUSY_WORDS.get(card["stage"], card["stage"])
    ctx.board.note(card["id"], f"{group}'s other {words(ctx)['change']} is raised too: {feature_id} reviews them "
                               f"together. This card is {where}, so it is not folded; you decide: "
                               f"archive it to take the feature review, or keep this one alone", ctx.actor)
    ctx.board.note(feature_id, f"{card['id']} ({label}) is {where}, so it is not folded; the user decides",
                   ctx.actor)
