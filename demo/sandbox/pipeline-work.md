# The sandbox work space's words for the pipeline's verify and preship steps

Included in a sandbox house's brief by `keel/review/brief.py`, under the steps of the same
name, because the sandbox's work space runs the pre-gate pipeline like any repo space.

## Verify
Run `python3 -m unittest` in each worktree that has tests, on the committed change, and put
the summary line under Evidence in the outcome. When the change shows on the reports page,
say what the page does now.

## Preship
Rebase onto `origin/main` in each worktree, and keep each repo's README true for what the
change adds.

## Publish
Then push and open the drafts, so the pull requests are up while the rest runs:
`git push -u origin HEAD` from every worktree of the card, then
`$KEEL_HOME/packs/sandbox/pr $KEEL_CARD`, which opens a DRAFT in each repo whose branch
is pushed. A rebase after this push is pushed with `git push --force-with-lease origin HEAD`.
