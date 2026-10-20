# Work space

You are in the work profile with the full toolkit. The repo's own `CLAUDE.md` and memory
apply. Personal content never reaches a work surface. The adapter's brief below carries the
repo-specific mechanics (worktree, tests, previews, pull requests); follow it.
Before the outcome gate you run Keel's pre-gate pipeline as its section in the brief says:
preship first (with the push and the draft), verify in the background, the review on that
head, risk. No work skill reviews the change a second time.

## Delegation

Delegate mechanical authoring to a cheaper model via a subagent with an explicit model
override: HTML, long prose, design-doc text to Sonnet; commit messages, branch slugs,
one-line blurbs to Haiku. Judgement (review, verification, design decisions) stays on your
model. Restate the writing rules in every subagent prompt: no em-dashes; use commas,
colons, parentheses, or separate sentences.
