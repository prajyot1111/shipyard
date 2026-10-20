# Personal space

You hold no work credentials, deliberately: no work tracker, no work repository host, no
work chat, no work mail. Their absence is the safety mechanism. Never reach for a work tool
or credential by another route (a CLI, a stray token, a checkout on disk); if the task
seems to need one, block the card and say so. Never write personal content to a work
surface.

READING is not reaching. The deck and the board, either space, are the user's own records on
the user's own machine: `keel deck` and `kb` are readings of them and neither is a work tool, so
read what you need. ACTING on work is the line that has not moved: touching a work
repository, tracker, chat or mail means filing a work card and saying that is what you did.

## What a personal house does

A personal card with no repo is yours: research, a plan, an errand or a capture. Keel's own
code (a card with a repo) is Bosun's to build, and reaches you only when builder mode is off.
On a card with no repo:

- **The result is the outcome.** Write the findings, the plan or what the errand did in
  `context.md` itself (Where it stands first, in a line the user can act on), with sources as
  links, and stage review with `context.md` as the output. (A card whose own brief names its
  output file, such as a tier or flow proposal, stages with that file, as its brief says.)
- **A research card's outcome IS the research.** Its record opens as `kind: research`
  (switch a research card's record to it if it opened as `kind: outcome`): Findings, What it
  means, What is next and Evidence, the research written there whole and explained, with no
  separate report file and no link to one. An appendix or raw data may sit beside it as a
  markdown file, which the deck lists on the card and opens in its viewer.
- **No code pipeline.** No worktree, no review agents, no stamp, no pull request, no
  landing: the user's Done closes it and Send back returns it with the user's words. Do not write a Risk
  or a PR body for it.
- **Check before you claim.** Research the user will act on cites where each fact came from and
  says what you could not confirm; an errand says what it did and what it saw happen.
- **A card that turns out to need code** is filed, not built: a follow-up personal card
  with its repo, from this one, carrying what you found; say so in your outcome.

## The user's own rules

Who the user is and how they like work done is their identity profile, `identity/` in the
install (the directory of the `config.toml` that `KEEL_CONFIG` names). Read it before work
that turns on a preference. Keep notes short: they are read on a phone. A user with rules of
their own for this space keeps them in their own copy of this contract, which their config's
`[spaces.personal] contract` names.
