"""The wait for a story's other side (lane GRP, GR-3): the old review scanner's hold.

When a review card is first filed for a pull request (or a feature) whose story has a
BRANCH, but no open pull request, in another reviewed repo, the other half is most likely
about to be raised, and reviewing one side alone would miss the seam between them. So the
card is filed Held: at the inbox, `options.review_wait` = {story, sibling_repo, since,
hours}, which the deck draws as "waiting for the <repo> PR (<story> has a branch there),
NNh left" (`views.review_wait`). Auto review never starts a held card.

Every poll, per held card, in this order, at most ONE read-only call to the adapter:

1. the window (`[spaces.<name>] review_sibling_hours`, 48) has run out: released, with
   "reviewed alone: the <repo> side was not raised in 48h";
2. the other side is raised but is not his to review (the scan's `open_groups`): released
   at once, since waiting would never end in a feature card;
3. `review branches <story> <member repo>...` (the scanner's `branches_with_story` query):
   the branch is gone, released; still there, the card stays held, nothing written.

The sibling raised AND needing him is not here: the fetcher then sees two members of one
story and files the feature card, folding this one into it (`keel/reviewfeature.py`). His
"Review now anyway" is the deck's `set` of `review_wait` to null and `review_alone` true,
so it ends the wait at once and the card is never held again. A released card is at
Detected (the inbox, waiting for his Review), or at assigned when auto review is on.
"""

from __future__ import annotations

from datetime import timedelta

from keel import terms, views

WAIT_OPTION = views.REVIEW_WAIT_OPTION
ALONE_OPTION = "review_alone"


def other_sides(ctx, group: str, member_repos: list[str]) -> dict[str, list[str]]:
    """The other reviewed repos' branches of the story: one call, {repo: [branch names]}."""
    found = ctx.ask("branches", group, *member_repos)
    branches = (found or {}).get("branches") if isinstance(found, dict) else None
    if not isinstance(branches, dict):
        return {}
    return {repo: names for repo, names in branches.items() if names and repo not in member_repos}


def wait_for(ctx, group: str, member_repos: list[str]) -> dict | None:
    """The wait a new card of this story starts with, or None: the first other repo that
    has a branch of the story and no open pull request of it."""
    raised = set(ctx.open_groups.get(group) or [])
    for repo in sorted(other_sides(ctx, group, member_repos)):
        if repo not in raised:
            return {"story": group, "sibling_repo": repo, "since": ctx.stamp, "hours": ctx.hours}
    return None


def line_of(wait: dict, left: int, t=None) -> str:
    """The wait in one line, in the space's words (`t`, c-630), as the deck's says it."""
    return (f"waiting for the {wait['sibling_repo']} {(t or terms.BASE)['change_short']} "
            f"({wait['story']} has a branch there), {left}h left")


def hold(ctx, card_id: str, wait: dict, said: str) -> None:
    ctx.board.set_fields(card_id, {"options": {WAIT_OPTION: wait}}, ctx.actor)
    ctx.board.note(card_id, f"{said}; held: {line_of(wait, wait['hours'], terms.of(getattr(ctx, 'cfg', None), getattr(ctx, 'space', None)))}. Review now anyway ends "
                            f"the wait", ctx.actor)


def tend_held(ctx, card: dict, member_repos: list[str]) -> None:
    """One held card, one poll: release it or leave it be (see the module)."""
    wait = views.held_wait(card)
    if wait is None:
        return
    since = views.parse_at(wait.get("since"))
    hours = int(wait.get("hours") or ctx.hours)
    repo, story = wait.get("sibling_repo"), wait.get("story")
    if since is None or ctx.at - since >= timedelta(hours=hours):
        release(ctx, card, f"reviewed alone: the {repo} side was not raised in {hours}h")
    elif repo in set(ctx.open_groups.get(story) or []):
        release(ctx, card, f"reviewed alone: the {repo} side of {story} is raised, and it is not yours to review")
    elif repo not in other_sides(ctx, story, member_repos):
        release(ctx, card, f"reviewed alone: the {repo} branch of {story} is gone")


def release(ctx, card: dict, why: str) -> None:
    """The wait ends: the card is at Detected, or assigned with auto review on."""
    ctx.board.set_fields(card["id"], {"options": {WAIT_OPTION: None}}, ctx.actor)
    if ctx.auto:
        ctx.board.stage(card["id"], "assigned", ctx.actor, note=why + "; auto review is on, so it is assigned")
    else:
        ctx.board.note(card["id"], why + "; tap Review to start it", ctx.actor)
    ctx.result["released"] = ctx.result.get("released", 0) + 1
