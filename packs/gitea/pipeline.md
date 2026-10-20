# This pack's words for the pipeline's verify, preship and publish steps

Included in a house's brief by `keel/review/brief.py`, under the steps of the same name,
for a space on this pack that names no pipeline of its own.

## Verify
Run the repo's tests as its CLAUDE.md says, on the committed change, and put the summary
line under Evidence in the outcome. Never start the app unless the repo's CLAUDE.md says how.

## Preship
Bring your branch up to its base without rewriting what is already pushed: fetch, then
merge the base branch into yours and resolve any conflict. Keep the repo's README and docs
true for what the change adds.

## Publish
Then push your own branch and open the drafts, so the pull requests are up and their
checks run while the rest goes on: `git push -u origin HEAD` from every worktree of the
card, then this pack's `pr <card> --draft` (your brief gives its full path), which opens a
DRAFT in each repo whose branch is pushed. Commits made after this are pushed the same
way. Never force a push, never push the base branch, never mark a pull request ready and
never merge one.
