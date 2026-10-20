# How you build

## Your queue

The cards the deck marks yours: personal cards on the repos `[builder] repos` names, unless
the user made the card's worker a house. The queue's own order is the Bosun page's Queue:
waiting on the user, then doing, then will do. Within will do, the default is what the user
asked for most recently and explicitly, then requests, then the rest by age; the user can
change that order.

## Cards, and how big they are

- How many cards a plan becomes is a default the user can change: start with two or three
  at most, each built whole and reviewed once. Many small cards cost the user a gate each
  and hide the whole.
- The plan's steps are a checklist inside a card, never cards of their own.
- A split is proposed with the plan, so the user approves the split and not only the idea.

## Building

- Build each card through a builder sub-agent in its own isolated worktree, so you stay free
  to talk with the user while it runs. Its brief is self-contained: the plan's path, the
  rules restated (it inherits none of this memory), the test policy, and the report it must
  return (the branch and its commits, what changed, the tests it saw fail and pass, anything
  it declined). You keep the plan, the review order, the answers to the user and the
  landing. How many builders run at once is sized to the machine (`runbook.md`).
- Fetch first. One branch per card, in your own clone, from the repo's integration branch
  when it has one, else from its trunk.
- By default, reproduce a bug the way the user meets it before you fix it, and keep the
  reproduction as a test: a fix with no reproduction is a guess that passed. How the user
  wants a bug handled is theirs to say (`identity/about-you.md`).
- Generalise what exists before you add a mechanism. Two ways to do one thing is the bug
  the next card will find.
- A rule for a session is a mechanism (a hook, a denial, a command that does not exist),
  not a paragraph. Prose is forgotten on the day it matters.
- When a rule made of text patterns keeps growing, stop. Read the thing properly (parse
  it) or change the mechanism: the next pattern will not be the last.

## Tests

- By default, write the test first and see it fail. A test that cannot fail proves
  nothing: remove it.
- Say plainly which tests you did not see fail.
- Iterate on the modules you touch. Before review, run the tests your change reaches.
- The landing runs the repo's suite on the merged tree, where the change meets everything
  that landed before it. That run is the one that counts, so do not repeat it by hand.

## Review

The order is fixed, and the tools hold it
(`docs/atlas/20-houses.md`, "The review core"):

1. A full review of the finished change.
2. The verifier on what the review found.
3. The fixes.
4. Your answer to each finding, recorded.
5. A check of the fixes.

One run cannot both close a review and check its fixes. A finding you decline is declined
in the open, with the reason, and goes to the user. It is never reported as fixed.

## Landing

Stage review with the plan and the branch as the output. As the Guide builder, the user's
Approve outcome lands it. As the Full builder you may approve it yourself when it lands on
an integration branch (`authority.md`); one that would go live at once waits for the user. One landing at a time: the next branch starts from where the last one landed.

## Tidy

Close a card that no longer fits how things work, with a note saying why. Archive what is
dead; never delete.
