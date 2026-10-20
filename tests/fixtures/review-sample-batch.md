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

```batch findings
q: What to post on the pull request
choices: post, edit, drop
r1-F1: `app/loader.py:40` The cap is read before the settings load, so it is always the default | post | high, kept by the verifier
r1-F2: `tests/test_loader.py:5` The test recomputes the cap the way the code does | post | medium, a tautological test
r1-F3: `app/loader.py:12` A local name shadows a builtin | drop | low, style only
```

```copy comment r1-F1
The cap is read at import time, before the settings are loaded, so it looks like it will
always be the default. Could it be read inside the call instead?
```

```copy comment r1-F2
This test computes the expected cap the same way the loader does, so it cannot disagree
with it. A literal from the settings fixture would catch a real regression.
```

```copy comment r1-F3
Small one: `list` shadows the builtin here.
```

## Snippets

```python app/loader.py:36-44 | where the cap is read, before the settings exist
CAP = settings.page_size()
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
