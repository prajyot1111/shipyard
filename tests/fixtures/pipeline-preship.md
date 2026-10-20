# A space's words for the pipeline's verify, preship and publish steps

A neutral stand-in for a pack's pipeline text (c-722), so the brief's order is held without
any pack of anyone's own. Its words are what the tests look for, under the step they belong to.

## Verify
Start these on the fixed head, each as a background job:
- the full suite, ONCE per trip, on the head that ships: the repo's own test command.

## Preship
For every endpoint the change adds or alters, update its docs and its `@api_docs` block.

## Publish
Then push and open the draft, so the code host's CI runs beside everything that follows:
`git push -u origin HEAD` from EVERY repo's worktree of the card, then
`$KEEL_HOME/packs/demo/pr $KEEL_CARD`, which opens a DRAFT in each repo whose branch is
pushed.
