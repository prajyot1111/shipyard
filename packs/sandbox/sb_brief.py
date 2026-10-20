"""`brief <id>` and `deny <id>`: the sandbox work house's half of its brief, and its fence.

The brief says where the house works, the story, and the ending: build and test, the
pre-gate pipeline, the pull request body in the record, the push to the bare origin, the
DRAFT pull request through this adapter's `pr`, and `kb stage review`. A review card gets
the read-only house and the review ending; a house started for a card already at shipping
gets the shipped ending. `METHOD` is how a house judges review on its pull request, printed
by `ship <id> method` for Keel to send with each batch (c-600).

The fence is the work adapter's, named for this adapter: a research card, a card at
shipping and a review card may not push, and may not run `pr` or `publish`; a review card
may not commit either. His Approve and his Ship are what publish.
"""

from pathlib import Path

from sb_card import (ADAPTER, HERE, base_of, branch_for, card_dir, is_research, is_review, option,
                     repos_of, story_of)
import sb_tracker

RULES = Path(__file__).resolve().parent / "rules"


def rule(name: str) -> str:
    """One of this pack's `rules/*.md`: the house's words live there as markdown (c-617)."""
    return (RULES / name).read_text()


HOUSE = rule("house.md")

ENDING = """\
## The ending

1. Build, then test (`python3 -m unittest` in each worktree that has tests). Commit on
   `{branch}` and end every commit message with a `Co-Authored-By:` line for yourself.
2. Run the pre-gate pipeline the section "Before you stage review" of this brief names.
3. Write the pull request body under `## PR body` in `{record}`, in a ````copy PR body
   block; a card with two repos writes one block per pull request, each titled with its
   repo (````copy PR body, web).
4. Push: `git push -u origin {branch}` from every repo's worktree.
5. Open the DRAFT pull requests: `{pr} {id}`. It opens one in each
   repo whose branch is pushed and records each on the card. Never mark one ready: the user's
   Approve outcome does that.
6. Finish: `kb stage {id} review --output <the first pull request's url>`, then end your turn.
"""

SHIPPED_ENDING = """\
## The ending: this card has shipped

Its pull requests are ready and the user approved the outcome. Keel tells you reviewers' comments
and failed checks in batches, each naming the method and how to record. Judge each item,
fix only what is valid with commits on `{branch}` (never push: it is refused at shipping),
record one `kb verdict {id} <handle>` per item, and end your turn. The user's Ship pushes your
commits and posts the replies they keep.
"""

METHOD = rule("comments.md")

REVIEW_HOUSE = """\
## Your house is a read-only checkout of a colleague's pull request

This card reviews pull request #{pr} in `{repo}`, `{branch}` into `{base}`: {url}. Your
worktree `{worktree}` is detached at its head. Never edit, commit or push.
"""

REVIEW_ENDING = """\
## The ending: your review, for the user to post

Write `{record}` in the plan format's review kind (`kind: review`): the summary, then
Orientation (a code-path board by id and a reading order), one ```finding block per
finding, and the ```decision verdict (comment, changes, approve, `other: no`). Then
`kb stage {id} review --plan {record} --output {url}` and end your turn. The user's Approve posts
what they keep.
"""


def compose(card: dict, worktrees: list[str]) -> str:
    record = card_dir(card["id"]) / "context.md"
    if is_review(card):
        pr = option(card, "review_pr") or {}
        fill = dict(id=card["id"], pr=option(card, "pr"), repo=(repos_of(card) or ["?"])[0],
                    branch=option(card, "branch"), base=base_of(card), worktree=worktrees[0],
                    url=pr.get("url") or "the pull request", record=record)
        return "\n".join((REVIEW_HOUSE.format(**fill), REVIEW_ENDING.format(**fill)))
    branch = branch_for(card)
    siblings = "".join(f" Also mounted: `{path}` for `{key}`." for key, path
                       in zip(repos_of(card)[1:], worktrees[1:]))
    parts = [HOUSE.format(worktree=worktrees[0], branch=branch, base=base_of(card), siblings=siblings)]
    story = story_of(option(card, "tracker_ref"))
    if story:
        parts.append(f"## The story\n\n`{story}`: {sb_tracker.url(sb_tracker.number_of(story))}\n")
    if is_research(card):
        parts.append(f"## The ending\n\nNever commit or push. Write `{record}` and stage review.\n")
    elif card.get("stage") == "shipping":
        parts.append(SHIPPED_ENDING.format(branch=branch, id=card["id"]))
    else:
        parts.append(ENDING.format(branch=branch, record=record, id=card["id"], pr=HERE / "pr"))
    return "\n".join(parts)


# This pack's own pr and publish, wherever it sits, and the sandbox's: a copy (`keel new
# pack`) keeps the sandbox's pipeline text until it is replaced (c-628 review r2.F4).
PUSH_DENY = ("Bash(git push:*)", "Bash(*git push*)", f"Bash(*{HERE}/pr*)", f"Bash(*{HERE}/publish*)",
             *(f"Bash(*{where}/{name}/{verb}*)" for name in dict.fromkeys((ADAPTER, "sandbox"))
               for where in ("adapters", "packs") for verb in ("pr", "publish")))
COMMIT_DENY = ("Bash(git commit:*)", "Bash(*git commit*)")


def deny_for(card: dict) -> list[str]:
    if is_review(card):
        return list(PUSH_DENY) + list(COMMIT_DENY)
    return list(PUSH_DENY) if is_research(card) or card.get("stage") == "shipping" else []
