---
kind: review
card: c-901
title: "Review: st-41001 · Tell the user which machines were refused"
repo: api, web
members: api#4150, web#2200
---
# Review: st-41001 · Tell the user which machines were refused

The backend refuses a machine with no sensor for the trigger and names it; the frontend
shows that refusal on every add path and unticks the refused machines.

## Orientation

The refusal starts in the backend's add route and ends in the frontend's toast, so the
path runs across both repos.

```board The refusal, from route to toast
b-2
```

Read it in this order:

1. `app/routes.py:12` api#4150: the add route refuses and names the machines
2. `src/definition.actions.js:30` web#2200: the action reads the refusal
3. `src/Details.js:88` web#2200: the toast and the untick

## Findings

```finding r1-f1
severity: high
member: api#4150
at: app/routes.py:40
claim: The refusal is a 400 with `uncoverable_ids`, the frontend reads `uncoverable_resource_ids`
evidence: the route builds the body at `app/routes.py:40`; the action reads the other name at `src/definition.actions.js:30`
verifier: kept
suggestion: Agree on one field name on both sides
comment:
  The route answers `uncoverable_ids`, while the frontend reads `uncoverable_resource_ids`
  (web#2200, `src/definition.actions.js:30`). Could the two agree on one name?
choice: post
because: high, a contract break the verifier kept
```

```finding r1-f2
severity: medium
member: web#2200
at: src/Details.js:88
claim: The toast names at most five machines but counts from the wrong list
evidence: "and N more" subtracts from the ticked list, not the refused one
verifier: kept
comment:
  The count after "and N more" is taken from the ticked list rather than the refused one, so
  it can be off. Could it count the refused ids?
choice: post
because: medium, kept
```

```finding r1-f3
severity: low
member: web#2200
at: src/Details.js:12
claim: A local name shadows a builtin
verifier: unverified
comment: Small one: `list` shadows the builtin here.
choice: drop
because: low, style only
```

## Verdict

```decision verdict-api-4150
q: What does your review of api#4150 say overall?
option comment: Comment only
  gets: the author reads the comment with no gate
  cost: the name mismatch could merge
option changes: Request changes
  gets: the field name is agreed before the merge
  cost: one more round
option approve: Approve the pull request
  gets: it can merge now
  cost: the frontend never sees the refused machines
rec: changes
because: the contract finding is kept and breaks the feature
other: no
```

```decision verdict-web-2200
q: What does your review of web#2200 say overall?
option comment: Comment only
  gets: the author reads the comments with no gate
  cost: the count stays off
option changes: Request changes
  gets: the name and the count are fixed first
  cost: one more round
option approve: Approve the pull request
  gets: it can merge now
  cost: the contract bug ships
rec: changes
because: it reads a field the backend does not send
other: no
```
