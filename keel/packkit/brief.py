"""`brief <id>`: the pack's half of a house's brief.

The brief says where the house works and the ending: build and test, the pre-gate
pipeline, the change's body in the record, the push of the card's OWN branch, the DRAFT
change through the pack's `pr`, and `kb stage review`. A house started for a card already at
shipping gets the shipped ending, and a review card's (c-730) the read-only checkout and the
review ending. `method()` is how a house judges review on its change (the pack's
`rules/comments.md`), printed by `ship <id> method` for Keel to send with each batch.

The house text is the pack's own `rules/house.md`; what a house is fenced from is the pack's
`guard` verb, which reads each command before it runs. Every sentence here says the pack's
word for a change and its host's name (`pack.words`).
"""

from keel.packkit import card as gc
from keel.packkit import pack, shared


def rule(name: str) -> str:
    return (pack.here() / "rules" / name).read_text()


def house() -> str:
    return rule("house.md")


def method() -> str:
    return rule("comments.md")


ENDING = """\
## The ending

1. Build, then run the repo's tests as its CLAUDE.md says. Commit on `{branch}` and end
   every commit message with a `Co-Authored-By:` line for yourself.
2. Run the pre-gate pipeline the section "Before you stage review" of this brief names.
3. Write the {change} body under `## {short} body` in `{record}`, in a ````copy {short} body
   block; a card with two repos writes one block per {change}, each titled with its
   repo (````copy {short} body, web).
4. Push your branch, and only your branch: `git push -u {remote} {branch}` from every
   repo's worktree. Never push `{base}` or any other branch, and never force a push.
5. Open the DRAFT {changes}: `{pr} {id} --draft`. It opens one in each repo whose
   branch is pushed and records each on the card.{draft_note} If you change the body afterwards, put
   it up with `{pr} {id} --body`. Never mark one ready and never merge one: Approve
   outcome marks it ready, and the merge is made {on} by a person.
6. Finish: `kb stage {id} review --output <the first {change}'s address>`, then end
   your turn.
"""

SHIPPED_ENDING = """\
## The ending: this card has shipped

Its {changes} are ready and the outcome was approved. Keel tells you reviewers' comments
and failed checks in batches, each naming the method and how to record. Judge each item,
fix only what is valid with commits on `{branch}` (never push: it is refused at shipping),
record one `kb verdict {id} <handle>` per item, and end your turn. Ship pushes your commits
and posts the replies that were kept. The merge is made {on} by a person, never by you.
"""

RESEARCH_ENDING = """\
## The ending

This is a research card: never commit, never push, and open no {change}. Write `{record}`
and `kb stage {id} review`.
"""


REVIEW_HOUSE = """\
## Your house: a read-only checkout of a {change} {on}

This card reviews {change} #{pr} in `{repo}`, `{branch}` into `{base}`: {url}. Your
worktree `{worktree}` is detached at its head. Nothing in it is yours to change.
Never edit, commit or push, and open no {change}: a push and this pack's `pr` are
refused here.

{reads}
"""

FORK_HOUSE = """\
## Your house: a confined checkout of a {change} from a fork

This card reviews {change} #{pr} in `{repo}`, `{branch}` into `{base}`: {url}.
It comes from a fork: code from outside the team. Your worktree `{worktree}` is detached at its head,
and your house is confined to it and your card directory. Read it, and never run any of it:
no build, no test, no script, no install. Your Bash runs the board and Shipyard's review steps
only, and the repo's own settings are not loaded. Approve outcome posts what the user keeps.
"""

REVIEW_ENDING = """\
## The ending: your review, for the user to post

Write `{record}` in the plan format's review kind (`kind: review`): the summary, then
Orientation (a code-path board by id and a reading order), one ```finding block per
finding, each `at:` a line of the change, and the ```decision verdict (comment, changes,
approve, `other: no`). Then `kb stage {id} review --plan {record} --output {url}` and end
your turn. The user's Approve posts the findings they keep on their lines, the summary
and the verdict, as one review {on}.
"""


def review_compose(card: dict, worktrees: list[str]) -> str:
    """A review card's house (c-730): the read-only checkout and the review ending."""
    words = pack.words().fill()
    url = (gc.option(card, "review_pr") or {}).get("url") or f"the {words['change']}'s address"
    fill = dict(words, id=card["id"], pr=gc.option(card, "pr"), repo=(gc.repos_of(card) or ["?"])[0],
                branch=gc.option(card, "branch"), base=gc.option(card, "base") or "its base",
                worktree=worktrees[0], url=url, record=gc.card_dir(card["id"]) / "context.md")
    reads = pack.host().said("review_reads", remote=gc.remote_of(card), **{k: v for k, v in fill.items()
                                                                           if k != "host"})
    house_text = FORK_HOUSE if gc.option(card, "review_fork") else REVIEW_HOUSE     # c-730 r2.F3
    return "\n".join((house_text.format(reads=reads, **fill), REVIEW_ENDING.format(**fill)))


def compose(card: dict, worktrees: list[str]) -> str:
    if gc.is_review(card):
        return review_compose(card, worktrees)
    record = gc.card_dir(card["id"]) / "context.md"
    keys = gc.repos_of(card)
    branch, remote = gc.branch_for(card), gc.remote_of(card)
    base = shared.base_in(card, keys[0]) if keys else "the base branch"
    siblings = "".join(f" Also mounted: `{path}` for `{key}`." for key, path in zip(keys[1:], worktrees[1:]))
    fill = dict(pack.words().fill(), worktree=worktrees[0], branch=branch, base=base, remote=remote,
                siblings=siblings, record=record, id=card["id"], pr=pack.here() / "pr",
                draft_note=pack.host().draft_note)
    if gc.is_research(card):
        ending = RESEARCH_ENDING
    else:
        ending = SHIPPED_ENDING if card.get("stage") == "shipping" else ENDING
    return "\n".join((house().format(**fill), ending.format(**fill)))
