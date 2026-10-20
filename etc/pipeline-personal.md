# The personal space's words for the pipeline's verify and preship steps

Included in a repo house's brief by `keel/review/brief.py`, under the steps of the same
name. The shape of the pipeline is Keel's; only these words are the space's. Only a card
with a repo runs it (`review.gate.wanted`): research, a plan or an errand has no code to
review, and with builder mode on a personal repo card is Bosun's, not a house's.

## Verify
Run `{tests}` in your worktree on the committed change, before the review step's agents and
again before a fix check: the review stamp records which suite ran at the head it names.
Where that is `make test-changed`, `make test` (the core suite and what the change reaches)
runs once, on the merged tree at Approve outcome, so a targeted green here is enough. Before you trust a green suite, reproduce the
change the way the user meets it: the command they would type, the page they would open
(`keel-browser shot`), the card they would move, and a bug fix starts with the reproduction
going red. Put the test output (the summary line and its wall time) and what the
reproduction showed under Evidence in the outcome, with any screenshot copied into `assets/`
beside it. Start ONE background subagent on the committed head beside the suite: it
redraws every board the plan embeds, pushes one `Code flow: <what>` board and writes the
board blocks and the numbered `path:line` reading order to `outcome-boards.md` in the card
directory, never into context.md. Merge it under Why this shape yourself, recheck its lines
on the final head, and join the subagent before you stage review (the plan section of your
brief says how; C33).

## Preship
On Keel itself, the Atlas page and the talker's memory say whatever the change makes true or
false, in the same commit; on any repo, so does its own documentation.
