"""The five cards that run beside the export card all day (c-807): two features, a bug fix
and two colleagues' pull requests under review, so the board shows six tasks moving at once.

They are BOARD STATE, as every seeded card is: the seed moves them through Keel's own Board
and the adapter's verbs, by the actor who would really make each move, and none of them
ever has a house session. The drain starts only a card at `assigned` and puts back only a
card that carries a `session_id`, so a seeded card at `building` is left exactly as seeded,
and the pools count only listed houses: the export card's house is still the only real
session of the day. The sandbox's drain is running while the morning is seeded, so none of
the five is ever at `assigned`, not even between two writes: each feature card is filed
straight at `building` (one write, its `create` event), and each review card goes from the
fetcher's `inbox` to `building` in one move, his tap's.

    morning   all five at building: the three cards just started, the two reviews tapped
              (their pull requests opened before the review fetcher's pass, which files them)
    evening   all five through their gate: each feature's draft opened and its outcome
              approved (shipping), the bug fix approved and merged (done), each review's
              findings at the gate, approved by the evening's own Approve of every review

Run again, each step is taken only from the stage before it, as the rest of the day is.
"""

from __future__ import annotations

from datetime import timedelta

from seeding.day import BoardKb, Day, SeedError, merge, open_pr, push_board, push_branch  # first

from keel import adapters  # noqa: E402

import sb_card  # noqa: E402
import sb_cut  # noqa: E402
import sb_host  # noqa: E402
from seeding import code  # noqa: E402

DARK = {
    "repo": "web", "branch": "feature/st-105/dark-theme", "author": "Robin",
    "subject": "Add a dark theme to the reports page",
    "files": {"theme-dark.css": '''/* The reports page in the dark, picked by the system setting. */
@media (prefers-color-scheme: dark) {
  body { background: #14161a; color: #e8e6e3; }
  table { border-color: #2c3038; }
  th { background: #1d2026; }
}
'''},
}

DIGEST = {
    "repo": "api", "branch": "feature/st-106/weekly-digest", "author": "Robin",
    "subject": "Email a weekly digest of the reports",
    "files": {"reports/digest.py": '''"""The weekly digest: the week's reports as one short text, ready to mail."""

from datetime import date, timedelta

from reports.store import all_reports


def digest(today: date) -> str:
    since = today - timedelta(days=7)
    rows = [r for r in all_reports() if r.created >= since]
    lines = [f"{r.title}: {r.total}" for r in rows] or ["No new reports this week."]
    return "\\n".join([f"Reports since {since.isoformat()}", *lines])
'''},
}

ROUNDING = {
    "repo": "api", "branch": "bug/st-107/totals-rounding", "author": "Robin",
    "subject": "Fix totals rounding on large reports",
    "files": {"reports/totals.py": '''"""Totals summed as integers, so a large report never drifts by a rounding step."""


def total_of(values) -> int:
    return sum(int(round(v)) for v in values)
'''},
}

OWNER_FILTER = {
    "repo": "api", "branch": "feature/owner-filter", "author": "Maya Chen",
    "subject": "Add an owner filter to /reports",
    "files": {"reports/owners.py": '''"""Filter reports by who owns them."""

from reports.store import Report


def owned_by(reports: list[Report], owner: str | None) -> list[Report]:
    if not owner:
        return reports
    return [r for r in reports if r.owner == owner]
'''},
}

EMPTY_STATE = {
    "repo": "web", "branch": "feature/empty-state", "author": "Tom Okafor",
    "subject": "Show an empty state when no report matches",
    "files": {"empty.js": '''// Under the table: a line when the search leaves no report.
function drawEmpty(reports) {
  const note = document.querySelector("#empty");
  note.hidden = reports.length > 0;
  note.textContent = "No report matches.";
}
'''},
}

# (spec, title, kind, tracker ref, merged by evening)
CARDS = (
    (DARK, "Add a dark theme to the reports page", "feature", "st-105", False),
    (DIGEST, "Email a weekly reports digest", "feature", "st-106", False),
    (ROUNDING, "Fix totals rounding on large reports", "bug", "st-107", True),
)
# (spec, title, pull request number, description): the numbers follow the morning's two
# reviews (api #12, web #31), so the export card's drafts are api #14 and web #33.
REVIEWS = (
    (OWNER_FILTER, "Add an owner filter to /reports", 13, "Adds `owner` to /reports: only that owner's reports."),
    (EMPTY_STATE, "Show an empty state when no report matches", 32, "A line under the table when a search finds nothing."),
)
TITLES = tuple(title for _, title, *_ in CARDS) + tuple(f"Review: {title}" for _, title, *_ in REVIEWS)
SHIPPING = tuple(title for _, title, _, _, merged in CARDS if not merged)

OUTCOME = """\
---
kind: outcome
card: {card}
title: {title}
repo: {repo}
---
# {title}

{said}

## Where it stands

Built and tested; a draft pull request is open in {repo}.

## Risk

Low: {risk}
"""

SAID = {
    "Add a dark theme to the reports page": ("The reports page follows the system's dark setting.",
                                             "one stylesheet, read only when the system asks for dark."),
    "Email a weekly reports digest": ("The api writes the week's reports as one short digest, ready to mail.",
                                      "a new module that nothing calls until the mail job is switched on."),
    "Fix totals rounding on large reports": ("Totals are summed as whole numbers, so a large report adds up exactly.",
                                             "one function, covered by a test with a report over a million."),
}

REVIEW = """\
---
kind: review
card: {card}
title: "Review: {title}"
repo: {repo}
pr: {pr}
---
# Review: {title}

{said}

## Orientation

```board {title}
{board}
```

1. `{path}:{line}` where the change is

## Findings

```finding r1-f1
severity: low
at: {path}:{line}
claim: {claim}
evidence: the change has no test for it
verifier: kept
suggestion: Add one test for it
comment:
  {comment}
choice: post
because: low, and a test keeps it true
```

## Verdict

```decision verdict
q: What does your review say overall?
option comment: Comment only
  gets: the note is posted and the author decides
  cost: none worth blocking on
option approve: Approve the pull request
  gets: it merges today
  cost: the case stays untested
rec: comment
because: only a low finding is kept
other: no
```
"""

REVIEW_SAID = {
    "Add an owner filter to /reports": dict(
        said="The change adds an `owner` query parameter to `/reports`, kept in a new `reports/owners.py`.",
        needle="r.owner == owner", claim="An owner is matched by exact case, so `maya` finds nothing",
        comment="Could the owner match ignore case, as the search now does?",
        ops='node app server "reports_for" "reports/app.py"\nnode owners file "owned_by" "reports/owners.py"\n'
            'edge app -> owners "owner"\nstep owners "A report is kept when its owner is the one asked for."\n'),
    "Show an empty state when no report matches": dict(
        said="The change adds a line under the reports table when a search leaves no report.",
        needle="note.hidden", claim="The note needs an `#empty` element the page does not have yet",
        comment="Is the `#empty` element coming in another change? The page has none yet.",
        ops='node draw box "draw" "reports.js"\nnode empty box "drawEmpty" "empty.js"\n'
            'edge draw -> empty "the rows shown"\nstep empty "The note shows when no row is left."\n'),
}


# ----- morning -----

def open_reviews(day: Day) -> None:
    """The two colleagues' pull requests, opened before the review fetcher's pass."""
    for spec, title, number, description in REVIEWS:
        open_pr(spec, title, description, day.ago(minutes=120), reviewers=["me"], number=number)


def morning(day: Day, filed) -> list[str]:
    """The three cards started and the two reviews tapped: all five at building, and never
    one at assigned, where the live drain would start a house on it."""
    ids = []
    for minutes, (spec, title, kind, ref, _) in zip((34, 31, 28), CARDS):
        day.at(day.ago(minutes=minutes))
        cid = filed(day, "work", title, brief=SAID[title][0], autonomy="autonomous", repo=spec["repo"],
                    model="opus", stage="building",
                    options={"kind": kind, "tracker_ref": ref, "branch": spec["branch"]})
        ids.append(cid)
    for minutes, (spec, title, number, _) in zip((26, 24), REVIEWS):
        card = day.card(f"Review: {title}")
        if card is None:
            raise SeedError(f"the review fetcher filed no card for {spec['repo']}#{number}")
        if card["stage"] == "inbox":
            day.at(day.ago(minutes=minutes))
            day.board.stage(card["id"], "building", "human", note="Review tapped")
            sb_cut.worktrees_for(day.board.get(card["id"]))
        ids.append(card["id"])
    return ids


# ----- evening -----

def reviews_at_gate(day: Day) -> None:
    """Each review's findings written and at the gate; the evening's Approve of every
    review posts them."""
    for spec, title, number, _ in REVIEWS:
        card = day.card(f"Review: {title}")
        if card is None or card["stage"] != "building":
            continue
        text = REVIEW_SAID[title]
        path = next(iter(spec["files"]))
        board_id = push_board(card["id"], f'board "{title}"\n{text["ops"]}')
        ctx = day.card_dir(card["id"]) / "context.md"
        ctx.write_text(REVIEW.format(card=card["id"], title=title, repo=spec["repo"], pr=number, board=board_id,
                                     path=path, line=code.line_of(spec["files"][path], text["needle"]), **text))
        day.board.stage(card["id"], "review", "house", plan_ref=str(ctx), output_ref=sb_host.url(spec["repo"], number))


def cards_through(day: Day) -> None:
    """Each card's draft opened and its outcome approved; the bug fix merged too."""
    for spec, title, kind, ref, merged in CARDS:
        card = day.card(title)
        if card is None:
            continue
        repo = spec["repo"]
        if card["stage"] == "building":
            push_branch(spec, day.now - timedelta(minutes=30))
            pr = sb_host.find_open(repo, spec["branch"]) or sb_host.open_pr(
                repo, f"{kind}: {title} [{ref}]", spec["branch"], "main", SAID[title][0])
            card = sb_card.record_pr(card, repo, pr["number"], kb=BoardKb(day))
            ctx = day.card_dir(card["id"]) / "context.md"
            said, risk = SAID[title]
            ctx.write_text(OUTCOME.format(card=card["id"], title=title, repo=repo, said=said, risk=risk))
            day.board.stage(card["id"], "review", "house", plan_ref=str(ctx), output_ref=pr["url"])
        card = day.board.get(card["id"])
        if card["stage"] == "review":
            day.board.approve(card["id"], "outcome", "human", publish=adapters.publisher(day.cfg, card["space"]))
        card = day.board.get(card["id"])
        if merged and card["stage"] == "shipping":
            number = card["options"]["pr"]
            merge(repo, spec["branch"], number, day.now)
            sb_host.set_state(repo, number, "merged")
            day.board.note(card["id"], f"pull request #{number} merged", "drain")
            day.board.stage(card["id"], "done", "drain")
