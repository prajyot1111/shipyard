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

```batch findings
q: What to post on the pull requests
choices: post, edit, drop
r1-F1: api#4150 `app/routes.py:40` The refusal is a 400 with `uncoverable_ids`, the frontend reads `uncoverable_resource_ids` | post | high, contract, kept by the verifier
r1-F2: web#2200 `src/Details.js:88` The toast names at most five machines but counts from the wrong list | post | medium, kept
r1-F3: web#2200 `src/Details.js:12` A local name shadows a builtin | drop | low, style only
```

```copy comment r1-F1
The route answers `uncoverable_ids`, while the frontend reads `uncoverable_resource_ids`
(web#2200, `src/definition.actions.js:30`). Could the two agree on one name?
```

```copy comment r1-F2
The count after "and N more" is taken from the ticked list rather than the refused one, so
it can be off. Could it count the refused ids?
```

```copy comment r1-F3
Small one: `list` shadows the builtin here.
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
