---
kind: review
card: c-900
title: "Review: Tidy the loader's page cap"
repo: api
pr: 4150
---
# Review: Tidy the loader's page cap

The change moves the loader's page size into one constant and reads it from the host's
settings, so a larger account no longer stops at the first forty rows.

## Orientation

The loader asked the host for forty rows at a time from two places; this change makes it
one constant, read once at start.

```board The loader's code path
b-1
```

Read it in this order:

1. `app/loader.py:12` where a page is asked for
2. `app/loader.py:40` the new constant and where it is read
3. `tests/test_loader.py:5` the one new test

## Findings

```finding r1-f1
severity: high
at: app/loader.py:40
claim: The cap is read before the settings load, so it is always the default
evidence: `CAP` is assigned when the module is imported, and the settings are loaded later, in `main()`
verifier: kept
suggestion: Read the cap inside the call that pages
comment:
  The cap is read at import time, before the settings are loaded, so it looks like it will
  always be the default. Could it be read inside the call instead?
choice: post
because: high, and the verifier kept it
```

```finding r1-f2
severity: medium
at: tests/test_loader.py:5-6
claim: The test recomputes the cap the way the code does
evidence: the expected value is the same expression the loader evaluates
verifier: disputed
  for: the expected value is computed by the code under test, so the two cannot disagree
  against: the fixture pins the settings, so the expression is a literal in effect
comment:
  This test computes the expected cap the same way the loader does, so it cannot disagree
  with it.

  A literal from the settings fixture would catch a real regression.
choice: post
because: medium, and a test that cannot disagree hides the next regression
```

```finding r1-f3
severity: low
at: app/loader.py:12
claim: A local name shadows a builtin
verifier: unverified
comment: Small one: `list` shadows the builtin here.
choice: drop
because: low, style only
```

## Verdict

```decision verdict
q: What does your review say overall?
option comment: Comment only
  gets: the author reads the comments with no gate
  cost: a high finding could merge unaddressed
option changes: Request changes
  gets: the high finding is fixed before the merge
  cost: one more round for the author
option approve: Approve the pull request
  gets: the author can merge now
  cost: the cap bug ships
rec: changes
because: the high finding is kept by the verifier and would ship the bug
other: no
```
