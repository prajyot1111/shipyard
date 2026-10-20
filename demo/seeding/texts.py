"""What the seeded cards say: the review outcomes, the plan at the gate, the export card's
outcome, and Bosun's fix. Each is a template filled with the card's id, its board ids and
the lines its findings point at. Written in the plan format, like every house's.

No em-dashes anywhere, and nothing names an employer: this is what the video shows.
"""

REVIEW_DATES = """\
---
kind: review
card: {card}
title: "Review: Add a date range filter to /reports"
repo: api
pr: {pr}
---
# Review: Add a date range filter to /reports

The change adds `from` and `to` query parameters to `/reports`, parsed as ISO days in a new `reports/dates.py` and applied after the title search, so a caller can ask for the reports created in a window.

## Orientation

`reports_for` reads the two parameters and, when either is there, passes the list through `in_range`, which parses each day and keeps a report whose created day falls inside. The handler is unchanged: it calls `reports_for` as before.

```board The date filter's code path
{board}
```

1. `reports/app.py:{app_line}` where the handler's list is filtered
2. `reports/dates.py:{parse_line}` how a day is parsed
3. `reports/dates.py:{range_line}` the comparison that decides the window

## Findings

```finding r1-f1
severity: high
at: reports/dates.py:{parse_line}
claim: A malformed day raises ValueError, which the handler does not catch, so the request fails with no answer
evidence: `date.fromisoformat("2026-13-01")` raises; `do_GET` has no handler for it, so the server logs a traceback and closes the connection
verifier: kept
suggestion: Catch the ValueError in `reports_for` and answer 400 with the parameter that was wrong
comment:
  `date.fromisoformat` raises on a malformed day (say `?from=2026-13-01`), and nothing
  catches it, so the client gets a dropped connection rather than an error. Could this
  answer 400 with which parameter was wrong?
choice: post
because: high, and a typo in a URL should not look like an outage
```

```finding r1-f2
severity: medium
at: reports/dates.py:{range_line}
claim: The end day is excluded, so `?to=2026-09-10` leaves out reports created on the 10th
evidence: the test covers `from` only; `r.created < last` drops a report whose day equals `last`
verifier: kept
suggestion: Compare with `<=` and add a test for a report on the end day
comment:
  `to` reads as inclusive, but `r.created < last` drops reports created on that day. Could
  it be `<=`, with a test for a report on the end day?
choice: post
because: medium, and it is the kind of thing that turns into a support question
```

```finding r1-f3
severity: low
at: reports/app.py:{app_line}
claim: The parsing could live in the handler, so `in_range` takes days rather than strings
evidence: `in_range` both parses and filters; the handler already owns the query string
verifier: kept
suggestion: Parse in `reports_for` and pass dates down
comment:
  Small one: `in_range` could take dates rather than strings, keeping the parsing next to
  the rest of the query handling.
choice: drop
because: low, style only, and not worth the author's time on this change
```

## Verdict

```decision verdict
q: What does your review say overall?
option comment: Comment only
  gets: the comments are posted and the author decides
  cost: the malformed day can ship as it is
option changes: Request changes
  gets: the two real problems are fixed before it merges
  cost: one more round for the author
option approve: Approve the pull request
  gets: it merges today
  cost: a bad day in the URL drops the connection in production
rec: changes
because: the high finding is kept
other: no
```
"""

REVIEW_TOTALS = """\
---
kind: review
card: {card}
title: "Review: Show report totals in the table footer"
repo: web
pr: {pr}
---
# Review: Show report totals in the table footer

The change adds a footer row to the reports table that sums the Total column of the rows on screen, redrawn with every search.

## Orientation

`draw` now ends by calling `drawTotal`, which adds up `report.total` over the rows it was given and writes the sum into the footer's last cell, a row added to `index.html`.

```board The totals footer's code path
{board}
```

1. `reports.js:{draw_line}` where the table is redrawn
2. `reports.js:{total_line}` the sum written into the footer

## Findings

```finding r1-f1
severity: medium
at: reports.js:{total_line}
claim: The total is written as a bare number, so 103713 shows with no separators beside the formatted cells
evidence: `textContent = total` writes the raw sum; the row cells come from the api as numbers too, but the footer is the one a reader scans
verifier: kept
suggestion: Write `total.toLocaleString()`
comment:
  The footer shows the raw sum (103713). Could it use `toLocaleString()` so it reads
  103,713?
choice: post
because: medium, and it is the number people will read out in meetings
```

```finding r1-f2
severity: low
at: reports.js:{total_line}
claim: The footer says Total while it sums only the rows the search left
evidence: `drawTotal(reports)` is called with the searched list
verifier: kept
suggestion: Label it "Total shown" when a search is active
comment:
  When a search is active the footer sums the visible rows only. Worth labelling it?
choice: drop
because: low, and summing what is shown is what a reader expects
```

## Verdict

```decision verdict
q: What does your review say overall?
option comment: Comment only
  gets: the formatting note is posted and the author decides
  cost: none worth blocking on
option changes: Request changes
  gets: the number is formatted before it merges
  cost: a round for a one-word fix
option approve: Approve the pull request
  gets: it merges today
  cost: the footer reads a little rough
rec: comment
because: only a medium finding is kept, and it does not block the change
other: no
```
"""

PLAN_PAGINATE = """\
---
kind: plan
card: {card}
title: Paginate the reports list
repo: api
at: {at}
---

# Paginate the reports list

The reports list is sent whole on every load, and the table draws every row. This plan pages it in the api, 25 at a time with a cursor, and gives the web page Next and Previous. One decision: the page size.

## Goal

The reports page loads the first page at once however many reports there are, and a reader can move through the rest.

## Now

- `/reports` returns every report in one answer: `reports/app.py:17`.
- The page draws whatever it is given, all at once.

## Target

- `/reports?page=<cursor>` answers one page and the cursor of the next.
- The table shows one page with Next and Previous.

## Proposal

A cursor, not an offset: the id of the last report on the page. A report added while someone pages does not shift what they see next.

```board The paging flow
{board}
```

## Decisions

```decision size
q: How many reports on a page?
why: It sets how much one load costs and how often a reader pages.
option p25: 25
  gets: a fast first load, and a page fits a laptop screen
  cost: more paging on a long list
option p50: 50
  gets: less paging
  cost: a heavier first load on a phone
rec: p25
because: the first load is what people feel
```

## Risks

- The web page and the api change together: the web half ships after the api half.

## Steps

```steps Build
[todo] Api | the cursor and the page size, with tests
[todo] Web | Next and Previous, the cursor kept in the URL
```

## Proof

- Tests for the first page, a middle page and the last.
- A shot of the table on its second page.

## Out of scope

- Sorting by anything but id.
"""

EXPORT_OUTCOME = """\
---
kind: outcome
card: {card}
title: Add CSV export to the reports page
repo: api, web
---
# Add CSV export to the reports page

The reports page has an Export CSV button, and the api streams `/reports.csv` a row at a time, with the page's search applied. One draft pull request in each repo, both waiting on your Approve.

## Where it stands

Built, tested and reviewed. Draft pull requests are open in api and web, and the story is linked below.

## What is next

Approve the outcome: both drafts go ready for review, the story moves to in review, and the card is shipping until both merge.

## Why this shape

The file is streamed rather than built in memory, as the plan settled: a long list never sits in the server's memory, and the first bytes reach the browser at once.

### What changed from the plan

Nothing: the button reuses the search box's words, as planned.

### Review findings

- Medium, fixed: a title with a comma broke its row. The writer now quotes it, and a test holds it.
- Low, left as is: the button could show a spinner while the file starts.

## Open questions

None.

## Evidence

The rows are written at `reports/export.py:{rows_line}`, and the suite in api:

```text | python3 -m unittest, in api
.....
----------------------------------------------------------------------
Ran 5 tests in 0.004s

OK
```

The button, on the reports page, downloads `reports.csv` with the header and five rows.

## Risk

Low: a new route and a new button; nothing that exists changes behaviour.

## PR body

````copy PR body, api
## Stream the reports as CSV

`GET /reports.csv` answers the reports as CSV, streamed a row at a time, with `q` applied like `/reports`.

- `reports/export.py`: the rows, a header first; titles with commas are quoted.
- Tests: the header, a line per report, a quoted title.

Story: {story}
````

````copy PR body, web
## Export CSV button

An Export CSV button beside the search box downloads what the table shows, searched or not, from the api's `/reports.csv`.

Story: {story}
````

## Links

- The story: {story}
"""

BOSUN_FIX = """\
---
kind: outcome
card: {card}
title: The publishable check reads each repo's branch in that repo's own clone
repo: keel
---
# The publishable check reads each repo's branch in its own clone

A two-repo card could not reach review: the publishable check looked for web's branch in api's clone, did not find it, and refused. It now asks each repo's own clone, and a test with two repos holds it.

## Where it stands

Fixed and tested; approved and landed on next.

## What is next

Deploy next to main, so the blocked card can stage review again.

## Why this shape

The check already walked every repo of the card; only the clone it asked was wrong.

## Open questions

None.

## Evidence

- The refused card's own move, replayed on a scratch board: refused before the fix, accepted after.
- The suite: green.

## Risk

Low: one lookup, covered by a new test.
"""

CACHE_BLOCK = ("kb stage review was refused: the publishable check looked for web's branch "
               "feature/st-104/cache-report-queries in api's clone and said it was not on origin, "
               "but it is: both branches are pushed")
