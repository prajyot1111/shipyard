# Flows

A flow says how a space's work moves from a card's branch to where it ends: the branches
and environments it passes through, the moves between them, and who makes each move (c-640,
c-639). Keel ships only general flows. A team's own flow is imported, per space, and set by
describing it in words: a house writes the file, Keel checks it, and you adopt it from
Settings. A card shows a button for each move you make, and the tap tells the card's house
what to do.

**What a flow does, and what it only draws (c-664).** Only the moves YOU make (`by = "you"`)
are buttons that act. Every other move (`house`, `keel`, `colleague`) is a PICTURE of what
the space's pack and Shipyard already do: nothing reads it but the drawing, and changing it in
the flow does not change what happens. What Approve outcome and Ship do is the pack's
(`publish`, `ship`) and Keel's own. So a flow cannot say who merges, squash or rebase, or a
condition such as "after one approval": it can draw them, and the Flow panel, the proposal
brief and `keel flow check` all say that a drawing is all it is.

Code: `keel/flows.py` (the format, which flow a space has, how it is drawn),
`keel/flowcheck.py` (whether a flow can run), `keel/flowcards.py` (propose and adopt),
`keel/flowmoves.py` (a move you make on a card), `keel/flowfence.py` (the push fence),
`etc/flows/` (Keel's own), `app/ui.settings.js` (the Flow panel) and `app/ui.cards.js` (the
buttons).

## The format

One TOML file per flow. `flows.parse` checks its SHAPE the way `packs.load` checks a
`pack.toml`: an unknown key is refused by name, and every reference must resolve. The key
lists in `keel/flows.py` (`TOP_KEYS`, `BRANCH_KEYS`, `MOVE_REQUIRED`, `MOVE_OPTIONAL`) are
the format: the check reads them and the proposal brief's short form is written from them.

```toml
name = "General"
description = "Branch from the base, a draft {change}, your approval publishes it."

[[branch]]
id = "card"              # lower case letters, digits and -, unique in the flow
label = "card branch"    # what the board shows; {base} is the card's base branch
kind = "card"            # card | work | base | integration | environment | trunk

[[branch]]
id = "dev"
label = "dev_review"     # no space in it: this label IS the branch's git name
kind = "environment"

[[move]]
id = "to-dev"
label = "Merge to dev review"
from = "card"
to = "dev"
by = "you"                   # house | you | colleague | keel
stages = ["review", "shipping"]
group = "Try it live"        # the button group on the card
pushes = ["dev"]             # the branches this move may push to (a move of yours only)
prompt = """Merge {branch} into {target} and push it. Resolve conflicts yourself."""
about = "Puts the card's work on dev review to try it live, before review is done."
```

| Key | Where | What it says |
|---|---|---|
| `name`, `description` | top | non-empty strings |
| `[[branch]]` `id`, `label`, `kind` | each branch | `kind` is card, work (a branch a move makes for the card's work, as a cherry-pick onto master), base, integration, environment or trunk. Exactly one has `kind = "card"`: a flow starts at the card's branch. An id is at most 48 characters and a label 120, so the board always draws them |
| `[[move]]` `id`, `label`, `from`, `to`, `by` | each move | `from` and `to` name declared branches |
| `step` | a `keel` or `house` move | the existing step it names: `publish`, `ship`, `land`, `deploy` (keel); `pr`, `push`, `rebase` (house). A keel move must name one, and a move by `you` or `colleague` names none. Drawn, and read by nothing else |
| `stages` | any; required for `you` | when the move applies: `assigned`, `planning`, `building`, `review`, `shipping`, `done` |
| `group` | any | for a move of yours, the button group it sits in on the card and on the card's pages: one group per name, "Decide" joins the card's Decide, none is Flow (c-644). On any other move it is drawn in the list and moves no button |
| `prompt` | `you` only, required | what the house is told, verbatim. It may name `{id}`, `{title}`, `{base}`, `{branch}`, `{target}`; any other field is refused |
| `pushes` | `you` only | declared branches the move may push to |
| `opens` | `you` only | declared branches the move may open a pull request to (c-641) |
| `bases` | any | names of bases: the move is offered only on a card whose `options.base` is one (the early merge is for a card based on the team's staging branch, not on master) |
| `about` | any | one line: the board's and the button's explanation |

**Who makes a move (`by`):**
- `you`: your tap, or your word to the talker. The ONE thing a flow does: a button on the card. `him` is the older spelling (c-640) and still loads, so a pack's file and a flow adopted before c-664 keep working; a parsed move, and the state the deck reads, always say `you`.
- `house`: the house, in its own pipeline (its draft pull request). Drawn only.
- `keel`: an existing Keel step (Approve outcome, Ship, the landing, the deploy). Drawn only: the step's own button is where it always is.
- `colleague`: someone on the code host (review, merge). Drawn only. A team's own flow means a teammate by it. Shipyard's general flow cannot know who, and the shipped connections say the user may be the one who merges, so the first run's drawing words it "you or a teammate" there (c-758, `app/ui.flowpicture.js`), and the move's `about` says "You or a teammate review and merge the {change} on {codehost_name}. Shipyard never merges it." in the space's own words.

**A label is the git name.** A branch's `label` with no space in it is its git name:
`{base}` (the card's base) and `{branch}` (the card's own branch) are filled per card, so
`{branch}-main` is a branch of the card's. A label in words ("integration branch") names no
branch: the push fence leaves it out, and no move can push it or open anything to it.

**The space's words.** Flow text may say `{change}` and `{Change}` (any key of the space's
`[terms]`, [packs](62-packs.md)): it is filled when the flow is read for a space
(`flows.of`), so Keel's general flow reads "draft pull request" in one space and "draft merge
request" in another (c-664). The noun guard (`tests/nouns.py`) reads `etc/flows/*.toml` too,
so Keel's own flows never spell the noun.

## A space's bases (c-732)

A team often cuts work from more than one branch (main and staging, say). A card's own base
(`options.base`) was the engine's already: the house's change is taken against it
(`house.target_of`), and a move's `bases` names the cards it fits. What was missing was the
choice: only a pack could offer it on the card form, and setup never asked.

- **The answer is the space's bases**, `[spaces.<name>] bases` (a setting, `keel/settings.py`,
  "Where work starts", each a branch name git takes by its own rule (`bases.branch_problem`, `git check-ref-format --branch`, the one rule a card's base is held to at create and at the cut too, r1.F12), each once; empty is the repo's default
  branch, as before). How work ships asks for it first ([onboarding](89-onboarding.md)), and
  Settings shows it with the space's other settings.
- **`keel/bases.py` is the one list.** `bases.of(space)` is the pack's own base select's
  options first (the work pack's two), else the space's own, else none. The card form (`cardspec.sheet` through
  `bases.row`), the flow draft (`flowcards`, both briefs), the provider draft
  (`packdraft.bases_said`) and How work ships all read it, so Bosun is told the same list in each
  draft (`bases.said`).
- **The card form offers Base branch** for every space that names bases, whatever its
  connection: a select of them, shown once the card names a repo, with NO default (r1.F5,
  F7): empty, said as "the repo's usual branch", is the repo's own rule, so a card that picks
  none is cut and landed exactly as before. "Another branch..." turns it into a box to type a
  branch the list does not name (`typed`, `app/ui.modal.js`, only on this row: a pack's own
  select with `custom` is drawn as it always was, r1.F2). A pack that declares its own base
  select keeps it exactly as declared (r1.F1: the work pack's select). A pack's FREE-TEXT
  base field (the GitHub pack's, a drafted pack's) takes the space's bases as its choices
  once the space names some (c-734, point 12: the box test's drafted pack did not offer
  them): a select of the bases that still takes a typed branch, with the pack's own label,
  help and placeholder (its blank); How work ships then asks for the bases as for a space
  with no pack (`firstrunsteps.bases_of`: `pack` only for a select of its own). A space that
  names none keeps the form it had.
- **In a space with no pack, a card that names a base is cut from it and lands on it**
  (`adapters.start_point`, `merging.landing_target`, `merging.footing`; a card naming none
  lands on the usual branch it was cut from, `options.cut_from`, r2.F1, see
  [onboarding](89-onboarding.md)): cut from the copy's
  branch of that name, else the remote's as last fetched, else refused by name, never a guess;
  landed plainly on that branch (the checkout keeps the branch it has out, and nothing else is
  merged in), and the Push offered after it pushes that branch. Fetch before work also moves a
  base the copy does not have out up to the remote's when it is strictly behind
  (`landpush.forward_base`), whatever happened to the trunk, both sentences joined on the card
  (r1.F10). A base that any working tree has out, the user's own linked one included (`git
  worktree list`, `merging.checked_out`), is never moved under it: fetch before work says so
  on the card and the card builds on this computer's, and a landing on it is refused with the
  path, nothing merged (r1.F9). A card that names no base is cut and landed as before.
- **Never on a repo with an integration branch** (r1.F4): there the integration branch is
  config and a card's base is refused at create and at set, and ignored beneath that
  (`merging.card_base`); the protection sits below Bosun's own outcome check, which is not
  this card's to change. How work ships offers no bases for such a space and names the
  integration branch ([cards and gates](10-cards-and-gates.md), "The integration branch").
  Saving bases for a space whose repos all land on one is refused (`settings.planned`, r2.F4).
  In a space where only some do, the Base branch row names the others (`repos`, from
  `bases.integrated` through `deckstate.options_for`) and the card form shows it only for a
  card on those, and the drafts are told the integrated repos name no base (`bases.said`). A pack's
  card was always cut and opened against its base by its pack.

## Whether a flow can run: `keel flow check`

`keel flow check <file> [--space <name>]` loads the file and then asks `keel/flowcheck.py`
what in it can never run. Each refusal names the move and says what to change. Adopt makes
the same check, always with its space, and the proposal brief tells the house to run it with
`--space`.

Always refused:
- a move of yours offered at `assigned` or `done`, where a card has no house (the tap would
  always be refused);
- `pushes` or `opens` naming the card's own branch, or a branch whose label is not a git name;
- a move whose `from` and `to` are the same branch.

Refused when the space is known:
- a `keel` step the space cannot run: `publish` or `ship` where its pack has no such verb,
  `land` in a space with a pack (its Approve publishes instead), any of the three where the
  space is held (`flows.held`, below, whose sentence the refusal carries), `deploy` where no repo of the
  space lands on an `[integration]` branch;
- `opens` where the space's pack does not declare `flow_pr` ([packs](62-packs.md),
  `[capabilities]`): its `pr` must take `--flow <branch> --to <target> --dir <worktree>`.

Loading a flow (`flows.of`) never runs this check, so a file adopted before it existed still
loads. Keel's own flows and the work pack's pass it in the spaces that draw them
(`tests/test_flows.py`, `<install>/packs/work/tests/test_flow.py`). The verb's last line says how many
moves are yours and that every other one is a picture.

## Which flow a space has

1. `<install>/spaces/<space>/flow.toml`: the space's own, written by Adopt (here, or on the proposal card).
2. `packs/<pack>/flow.toml`: a pack's default, by convention (no `pack.toml` key).
3. Keel's own, from `etc/flows/` (`flows.default_of`, c-664):
   - `general.toml`: only a space whose pack reaches a code host (`flows.hosted`): it
     declares `codehost` (`readiness.refusal`, as `adapters.publish` asks), or it is an
     older adapter with no `pack.toml`, which declares nothing, and has BOTH the `publish`
     and the `ship` verbs. An older adapter without both is held (below). It has no move of
     your own, so it adds no button; Approve outcome and Ship, which it draws, are the
     card's own buttons.
   - `integration.toml`: a space with no code host whose EVERY repo lands on an
     `[integration]` branch, as Keel's own does.
   - `local.toml`: any other space, where Approve merges into the checkout's branch on this
     machine and nothing is pushed.

   Both landing flows say "It is merged locally, not pushed." (c-665): a landing pushes
   nothing.

   **Fetch before work, and a Push by the user's tap** (c-678, `keel/landpush.py`). For a
   repo the install copied into its own layout, in a space with no pack, two switches of
   the space. Both default off, so an install set up before them does not start fetching by
   itself; the first run writes both on for the space it makes (`onboarding.add_space`):
   - `fetch_before_work`: when a card's worktree is cut (`adapters.personal_worktrees`),
     Keel fetches the space's remote in its copy and fast-forwards the copy's branch when it
     is strictly behind (`landpush.fetch_first`), so the card builds on what the team has.
     It never refuses a card: a fetch that fails, or a copy that has moved too, is a
     sentence, and the card builds on what this computer has. The sentence is a note on the
     card (`adapters.say_on_card`) and a line of the house's brief ("When this worktree was
     cut", `house.cut_block`). The fetch has 20 seconds to answer (`FETCH_FIRST_SECONDS`),
     since it runs in whoever cuts the worktree.
   - `offer_push`: a done card whose landing was a local merge carries `push` on its detail
     (`landpush.offer`, `/api/card/<id>`): the branch, the remote, and whether the remote
     has the landing, read from git each time (the landed commit is in the copy's
     remote-tracking branch), never stored. The pane says "Merged into main on this
     computer." with the one button "Push main to origin" (`K.pushBlock`,
     `app/ui.landpush.js`). The button is the page's verb `land.push` {`id`, `fetch`?}
     (`actions.SETUP_TABLE`), a plain `git push` (by the remote's address, below) that never asks for a password and is
     never forced: the landing still pushes nothing by itself.

   A push the remote refuses because it has commits this computer has not seen says
   "origin has commits this computer has not seen, so the push was refused." (the refusal
   carries `detail.kind` `behind`), and its fix on the card is Fetch and try again: the
   same verb with `fetch`, which fetches, builds the merge of the remote's branch onto the
   copy's on a temporary tree, runs the repo's prepare and test commands there
   (`keel/repocommands.py`, the tests told the commit the merge was built on), moves the
   copy's branch only if it has not moved meanwhile (`merging.settle`), and pushes. Commits
   that change the same lines are not merged (kind `conflict`), red tests merge nothing
   (kind `tests`), and either way the copy is as it was and nothing is pushed. A folder the
   user attached is the user's own checkout: Keel neither moves its branch nor pushes from
   it (`landpush.applies`).

   **The copy cannot be pushed to** (c-729, point 17). On the stranger run the user's
   remote held a card's branch, which its house had pushed by hand. Teaching the guard to
   read where a shell line's push really runs opened a new way round it each round, so the
   mechanism is git's own: the copy's remote has a push address git has no helper for,
   `remote.<name>.pushurl` = `no-push://set-by-shipyard` (`landpush.NO_PUSH`,
   `landpush.fence`), set when the copy is made (`reposetup.clone_repo`) and reconciled at
   every card cut, whatever the space (`adapters.worktree`): fenced in a space with no pack,
   pushable again in one with a pack (its pack pushes for it), however the pack line got
   into the config; `packsetup.pack_on` does the same at once. A push address the user had
   set on the copy is kept under `remote.<name>.shipyardPushurl` (`landpush.SAVED`) while
   fenced and put back after. Every `git push` to that remote, from the copy or any
   worktree of it, fails however it is written; a fetch is untouched. The Push, the check
   "This computer can push to origin", and a flow move the user tapped (`kb flowpush`,
   `flowfence.push`) push by `landpush.push_to`: to the saved push address when there is
   one, else the remote's own address (`remote.<name>.url`), never through the fence, and
   the copy's remote-tracking branch records it as a push to the remote would. A folder
   the user attached is never fenced. It keeps card branches off
   the user's remote by accident, and is not a security fence: a push straight to an
   address, or one that adds a push address with `-c`, still goes through.

   **The plain push runs in the tap; the one that brings commits in does not** (c-678
   review). A plain push is one git command. Fetching, merging, preparing and testing can
   take as long as the repo's whole suite, and inside the deck's request it held the lock
   every setup verb waits on. So `land.push` with `fetch` marks the card
   (`options.push = {state: "testing", host}`, the drain's to write, like
   `options.landing`) and returns at once, and a worker in a session of its own does the
   work (`landpush.start`, `landpush.work`, `python3 -m keel.landpush <card> --tap <event>`,
   started the way a landing's worker is, `landing.spawn`). **The worker pushes only for the
   user's tap** (review r2.F2): the verb writes the user's own event on the card (a note by
   the human actor, "asked for the push, with origin's commits fetched and merged in
   first") and puts its id in the mark and on the worker's argv. `landpush.asked` lets the
   worker go on only when that event is on this card, the mark is `testing` for this
   machine with that id, no pid is on it yet, and it is under a minute old; otherwise it
   writes nothing, pushes nothing and says so in its log. Taking the tap is one
   conditional write (`landpush.take`: an UPDATE that changes the row only while the mark
   is still the untaken one), so two workers cannot both take it, a tap is good for one
   worker, and the command typed by hand or by a session finds nothing to take. A mark
   nobody took in a minute reads as a worker that is gone. It puts
   its pid and the time it started on the card, holds the
   checkout's lock (one landing, pre-run or push per checkout at a time,
   `landing.repo_lock`), and answers on the card: a note, and the mark `pushed` or
   `refused` with the kind and the sentence. The card's detail carries it (`push.testing`,
   `push.refused` on `/api/card/<id>`), so the pane says "Bringing in origin's commits and
   testing them with yours. This page follows it." with no button while it runs, and a
   refusal is still on the card after a reload. A mark whose worker is gone (its pid is not
   running, or it never wrote one in five minutes, or the process with that pid started at
   another time than the worker did, `landpush.born`, since a pid is handed out again) is
   read as a refusal, "The push stopped before it finished, and nothing says why. Try
   again.", never as testing for ever. While a worker is testing, a plain push is refused
   too ("<card> is already being tested for its push"), so nothing writes over its mark and
   no second worker starts beside it. A
   refusal a retry would only repeat has no retry button: `conflict` (its sentence says a
   card on the repo can merge them) and `tests`.

   Where the design and the code differ: the design's second fix for a refused push, "Send
   back to the session to merge", has no place, since the card is done and its session is
   over; the refusal for commits that disagree says a card on the repo can merge them.

   **A held space** (`flows.held`) is one with a pack or an adapter for which Keel draws
   no flow. `held` is one whole sentence, true of its own case, carried on the state as
   `flow.held` whatever the flow's source:
   - **its pack declares no code host** (a tracker only, or a `pack.toml` that does not
     load): `adapters.publish` REFUSES Approve of a repo card, and nothing is merged
     locally either. "A repo card cannot be approved in this space until a code host is set
     up (...)", the reason being `readiness.refusal`'s.
   - **an older adapter with no `publish` verb**: it declares nothing, so it is not
     refused; Approve runs the adapter and FAILS on the missing executable. "Approve of a
     repo card fails in this space: the <name> adapter has no publish verb."
   - **an older adapter with `publish` and no `ship`**: a card IS approved and published,
     and goes to shipping on the publish answer alone, where your Ship runs `publish`
     again; `ship` is only the watcher's verb (poll, reap, sync), so Keel cannot watch the
     card there. "A card can be approved and published in this space, but Shipyard cannot
     watch it at shipping: the <name> adapter has no ship verb. So Shipyard draws no flow for
     it."

   Keel's own flow for a held space is the local merge with NO move drawn and the
   description "Shipyard draws no flow for this space yet." The Flow panel prints the held
   sentence as it is, once, in a line of its own with Set it up (the first run's
   Where finished work goes step), also for a space whose flow is its own or its pack's file. The
   check refuses a `land`, `publish` or `ship` move for such a space with the same
   sentence.

**A landing branch is drawn by its name** (`flows.drawn`, drawing only). The integration
flow's branch is drawn as the branch `[integration]` names (`next`). A space where only SOME
repos land on one draws the local merge, with that branch and its repos named beside the
base ("the card's base, or next for keel") and one more sentence in the description, so the
drawing is true of every repo. The files keep those labels in words, which name no git
branch: the push fence and the landing read nothing new.

A flow file is parsed once per change: `flows.load` keeps it by its path and stamp (mtime and
size). A file that does not load (bad TOML, not UTF-8, a check that fails) is skipped and said: `spaces[<name>].flow.warnings`, and Now's
config warnings panel through `config.warnings`. The next source is then used, so a broken
flow never stops the deck. A flow is read in every state build, so an adopted flow shows on
the next state, with no restart. `keel flow show [space]` prints each space's flow as the
deck draws it.

`/api/state` carries `spaces[<name>].flow` (`flows.drawn`):
- `name`, `description`
- `source`: `space`, `pack` or `keel`
- `branches`
- `moves`: with `from`, `to`, `by`, `step`, `stages`, `group`, `pushes`, `opens`, `bases`, `about`. The prompt stays on the server.
- `warnings`
- `held`: why Keel draws no flow for this space, as one sentence, or null (above).
- `held_codehost`: true when that reason is the first case, a pack that loads and declares no code host (c-758 r1.F8, `flows.no_codehost`; r2.F2: a pack that does not load declares nothing and is not this case): the first run's How work ships advises choosing another connection or this computer for that case only, and shows the sentence alone for the other two.
- `handling`: how the space treats review at shipping, which no flow says: `shipping`
  (whether Keel publishes and watches a card here at shipping: `flows.hosted`, and its pack
  has the `ship` verb), and `comments` and `checks`, the space's two automatic-handling
  settings.
- `landing`: `{repo: branch}` for each of the space's repos that lands on an `[integration]`
  branch (`flows.landing`; empty for a space with a pack), whatever the flow's source.
  **The deck spells no branch name of its own** (c-665): a line that names a card's landing
  branch reads it here (`K.landsOn(space, repo)` in `app/ui.core.js`: the pane's worker line,
  the card form's Worker row, a Keel card's "on `<branch>`" word), the
  Bosun page's Shipped section reads the deploy ask's own `target` and `trunk`
  (`deployask.brief_of`), and the sentence after an approve that conflicted names the branch
  the refusal named (`actions.merge_conflict`, `target`). Where the name is not known the
  line is said without one ("lands it", "merging its target", "the trunk"), never with a guess.
- `proposal`: the open proposal (`{card, stage, waiting}`), or null.

## What a flow does not cover at shipping

A flow draws shipping as one `keel` move, Ship. What you can actually press on a shipping
card is the engine's and the pack's, the same in every flow, and no flow file changes it
([cards and gates](10-cards-and-gates.md), "Review at shipping"; [the drain](30-drain.md),
"Shipping"; [the comments page](67-comments.md)):

- **Ship, named by what it sends.** The button says what the tap will do (push the commits,
  mark the pull request ready, post the replies you kept), and is not offered when there is
  nothing to send.
- **Ship anyway.** A Ship that is held (commits no review stamp covers, a conflict with the
  base, items still being judged) says why, with Ship anyway one tap from that line.
- **The hand-over.** Review that arrives while the card waits (comments, a review asking for
  changes, a failing check) is KEPT on the card until you hand it to the house ("Hand 3
  comments and the failing check to the house"), and "Bring the branch up to its base" asks
  the house to merge the base in.
- **The two automatic-handling settings**, both OFF by default: `ship_auto_comments` and
  `ship_auto_checks`, per space, with a card's own option over them. On, that kind goes to
  the house as it arrives. They are Settings, not flow; the Flow panel says their state and
  links to them. In a space with no pack no card reaches shipping, so they do nothing there,
  and the panel says so, naming one that is turned on. In a held space the panel's note says
  only "Shipyard draws no flow here, so it says nothing of shipping; see the line above".
- **A branch that has diverged from its pull request's branch refuses the whole Ship**,
  with the one sentence the card, the refusal and the deck all carry and the commands to
  bring it in line by hand. Keel never rebases or forces. A move of yours that `pushes` is
  refused in that state too (below).
- **A house started afresh.** A shipping house whose conversation the harness no longer
  holds is started again from the card's record. A standing grant survives it (it is on the
  card), but the move's prompt was told to the old conversation: tap the move again.

## In Settings

Each space has a **Flow · \<space>** panel after its settings:
- The flow's name, where it comes from, and its description; then the line saying that only
  the moves you make are buttons and the rest is a picture (and, for a flow with no move of
  your own, that it adds no button: Approve and Ship are the card's own). Each move's line
  says who makes it in the first run's words (c-758 r1.F6, `whoOf`): Approve and Ship are
  "you · the card's own button", a step on the code host is "a teammate" in a team's own
  flow and "you or a teammate" in Shipyard's general flow.
- The flow drawn as a board, through `K.boardDraw.drawGraph`: a node per branch, one edge per move labelled with it and who makes it, and a branch a move of yours reaches is marked. A raw `{base}` is drawn as "the card's base" (`K.flowLabel`).
- The moves listed, each with who makes it and whether it is a button or drawn only, from and to, its stages and its line.
- **Review at shipping**: the state of the space's two automatic-handling settings in words,
  with a link to them (`flow.handling`); in a held space only "Shipyard draws no flow here, so
  it says nothing of shipping; see the line above"; or, in a space with no pack, that they do
  nothing in this space, naming one that is turned on.
- Under that, **Describe how your team ships**: your words, then **Propose**. The example in
  the box is a neutral one (a small team on main with pull requests).
- While a proposal is open, the panel shows it instead (below), with **Adopt** once the draft is ready (the card's own Adopt button is the same tap).
- A space with a flow of its own also has **Use the pack's or Shipyard's flow** (`setup.flow.reset`), which renames its file to `flow-<stamp>.toml.bak`, never over an earlier one.

**The Settings layout** (c-640: labels at the far left and controls at the far right are hard to tell apart, so they sit together):
- **A field** is a label column (the name, then its help, always shown) beside a control column, left aligned, in a measure of at most 760 px.
- **On the desk,** a sticky list of the sections sits beside the fields.
- **The deck's space comes first** (its settings, then its flow), each space's row and each Flow panel carries the space's chip, and a pending change is marked and saved from a bar stuck to the bottom (c-661, [the deck](40-deck.md), "Settings: which space, and what is unsaved").
- **On the phone,** it is one column with 44 px targets.

## Propose and adopt

This is the tier card's pattern ([onboarding](89-onboarding.md), c-618).
- **Propose:** `setup.flow.propose` (`{space, words}`) files a personal errand, `Propose the <space> flow`, with `options.flow_proposal = <space>`. Its brief carries:
  - your words, verbatim;
  - the space's current flow, copied to `state/cards/<id>/flow-current.toml`;
  - what a flow is and is not: only a move by `you` acts, the rest is a picture, and what the words ask of a drawn move is drawn and said on the card as not carried out;
  - the format in short, written from the schema's own key lists (`flowcards.format_text`), so it names every key (`opens` and `bases` among them) and the rule that a label is the git name; it points to this page, which is also its plan.

  The house writes `state/cards/<id>/flow.toml`, runs `keel flow check <file> --space <space>` on it, and stages review with it as its output. One open proposal per space.
- **Adopt:** `setup.flow.adopt` (`{card}`, `onboarding.adopt_flow`) refuses a space that is not configured here, reads the file ONCE, checks its shape and whether the space can run it (the same check, `flowcheck.check`), writes exactly what it checked to the space's `flow.toml`, approves the card's outcome and stops its finished house, as tier Adopt does. A proposal that does not check is refused, and nothing is written.
- **The proposal card's own outcome button** reads **Adopt** and is Adopt: the deck's tap (`actions.act_approve`) and your `kb approve <id> outcome` (`cli.approve_proposal`) both call `onboarding.adopt_proposal`, the function the Adopt button here calls, for a flow and for a tier alike (c-667, [onboarding](89-onboarding.md), "Approve outcome on the card is Adopt"). A draft that does not check refuses the tap and leaves the card at review; a second tap on a draft already adopted writes nothing and says so; and no other move closes a proposal (a stage move to done is refused: "it closes by Adopt, which writes its draft; archive it to drop it"), so a proposal never closes without its draft written. Any approve but yours is refused: Bosun's by the board (`Board._approve_as_bosun`).

**A draft Bosun writes with the user (c-678).** The first run's How work ships step has no
box to describe a flow in: the user tells Bosun in its session, and what they agree comes
back to that page as a picture to accept ([onboarding](89-onboarding.md), "How work
ships"). It is optional, and the page says so (c-758): the flow the space already has is
drawn first, headed as already set, and the draft is offered below it under "Only if your
team works differently"; the step is done without it. The mechanism is the proposal card with another worker, as a tier's draft card is:
- `setup.flow.draft` {`space`} (`flowcards.open_draft`), the user's tap on Open a draft for
  Bosun, files `Draft the <space> flow` in personal with `options.flow_proposal = <space>`
  and `options.flow_draft`, at `inbox`, so the drain starts no house on it. Only the user
  may make a proposal card, which is why the page files it and Bosun does not. One open
  proposal per space, as for Propose.
- Its brief (`flowcards.DRAFT_BRIEF`) tells Bosun to ask how the team ships, one question at a
  time with its example, the questions How work ships shows (`bases.ASKS`), and to ask back
  whatever it cannot place rather than guess; it names the space's bases (`bases.said`), gives
  the space's flow today as a file and the format from the schema's own lists, asks for a
  `description` in the user's own words and an `about` on every move (the page draws it and
  reads the arrows back as a sentence), and says where to write: `<install>/builder/cards/<id>/flow.toml`, Bosun's own folder for the card.
  Bosun runs `keel flow check <file> --space <space>`, stages the card `building` when it
  starts and `review --output <file>` when it checks.
- `flowcards.draft_path` finds the proposal in one of two fixed places, the card's own
  directory (a house's) else Bosun's folder, so Adopt, the card's outcome button and the
  page all read the same file and no card can point Adopt at a file of its choosing.
- `flowcards.shown` is what the Setup report carries per space (`spaces.<name>.flow_draft`):
  the open proposal's card and stage, and, once it is at review, the draft drawn as the
  deck draws a flow, checked for the space first. A draft that does not check is `error`,
  in the check's words, and is not drawn.

Adopt is the same `setup.flow.adopt` as for a house's proposal.

**What Propose says (c-664).** A new user may think they say it once and leave. So every
Propose on the deck says the same three things, from one helper (`K.proposing`,
`app/ui.setup.js`), used by this panel, the tier proposal and the import
([onboarding](89-onboarding.md)):
- **Before the tap, beside the button:** Propose files a card of its own, and a Claude
  session (a house) starts on it when one is free; it reads what you wrote and writes a
  draft; nothing changes until you Adopt it, with the Adopt button beside the proposal or
  the one on its card.
- **After the tap, where it went:** the card's id as a link to it, and its state in words:
  "will draft ...: waiting for a session to start" while the card is assigned (no session
  exists yet, so it says you can open the card now and type into its session once it has
  started, never to Drop in; the import's says it waits for Bosun to be started), then working (planning
  or building), waiting for you (it blocked on a question), draft ready (review).
- **That it is a conversation:** open the card and use Drop in to type into that session;
  when the draft is ready, Adopt it or Send back with what to change (the outcome gate's
  Send back takes the card back to building and resumes the same session with your reason),
  as many rounds as you like.

## A move you make

**The tap.** `flow.move` (`{id, move}`, `actions.act_flow_move`, `keel/flowmoves.py`) is a house verb, so a house's own `kb` cannot call it. It is refused when:
- the space's flow has no such move;
- the move is not yours;
- the card is not at one of its stages;
- the card is blocked;
- the card has no house;
- the move `pushes` and the card is at shipping with a record saying its worktree is behind
  its pull request's branch or has diverged from it (`options.shipping.local`, read only,
  c-664): the refusal is the record's own sentence, since the house would push that old
  history to a shared branch. Only at shipping: the drain keeps the record fresh there, and
  no stage move drops it, so one left on a card back at building or review is not believed.

**What it does.**
1. It notes the move on the card.
2. It sets `options.flow_move = {id, pushes, opens, names, labels, stages, at}`, the grant a pack's fence reads to let that move push only to the branches it names (c-641). `flow_move` and `flow_proposal` are among the board's human-only options (`HUMAN_ONLY_OPTIONS`), and refused at create too for any actor but you (`HIS_AT_CREATE`, with `tier_proposal`, c-667), so a house cannot grant itself a push or aim an Adopt, on its own card or on one it files. The grant is written before the tell, so a house told at once finds it, and when the tell is refused or fails it is put back as it was before the tap.

   **How long a grant lasts:** until the card moves stage (`Board._move` drops it on any move to another stage, done included), your next tap replaces it, or the flow changes under it: the grant keeps what the flow called each branch at the tap (`labels`, beside the names filled from them), and `flowfence.info` ends a grant whose flow labels one differently now, saying the flow changed since the tap (c-664). Only the flow ends it: a card whose base or branch reads differently for a moment keeps its grant and its tap-time names. The option stays on the card, so the work pack's own `pr --flow` asks `kb flowinfo` before it opens anything (`pulls.standing_grant`) and refuses in the board's words. A move you make is for the stage you tapped it at.
3. It tells the house the move's prompt, filled with the card's `{id}` and `{title}`, its `{base}` (`house.target_of`), its `{branch}` (`options.branch`, else the branch its outcome names) and the move's `{target}`. A fact it cannot read stays as written, never empty. It tells it exactly as Resume does: told in place when idle, resumed when exited, held for the turn's end when working, and relayed to the drain. The house is asked to say on the card what it did.

**Your word.** `kb flowmove <id> <move>` (c-641) is the same tap made on your word: the talker runs
it as `kb --actor voice flowmove ...` when you name a move and a card (its rulebook,
`<install>/memory/talker/shipping-a-work-card.md`). It calls `actions.act_flow_move`, so the grant and
the tell are the tap's. Its actors are `human`, and `voice` WITH your token (`KEEL_TOKEN`, as a
voice answer that approves carries it, `cmd_console`): `--actor voice` alone is a name anyone
may type. A house and Bosun are refused.

**The buttons.** The deck draws them as `flow-<move>`, by the card's OWN stage (the server's check, never a parent's), in the group its move's `group` names (c-644: one split button per name, in the order the flow first names them; "Decide" joins the card's Decide; a move with no `group` is under **Flow**), each with its `about` as its line. A move that names `bases` is drawn by the base the server says applies, which each card in the state carries as `base` (`deckstate.base_of`, `merging.card_base`: none on a repo with an integration branch, whatever `options.base` holds; c-732), never the option as stored. The card's viewer draws the same moves under the title of each page (`planroute.moves_of`, `K.flowBar`). The `flow` row of [the deck's](40-deck.md) controls by phase allows every phase, because each move says its own stages.

## The push fence (c-641)

A flow says which branches are SHARED: every branch whose kind is not `card` or `work`. A
house never pushes one by hand, and `keel/flowfence.py` makes that a mechanism:

- **The board judges.** `kb flowinfo <id>` (`flowfence.info`; also the read verb `flowinfo`)
  answers the card's stage, its flow's shared branches as git names (a label in words, "integration branch",
  names no branch and is left out), and the move of yours it may carry out now, or why not. The
  grant itself records the git name of each branch the move
  may push or open (`names`, filled at your tap, and ending the grant once the flow names them differently), which the pack checks too.
- **The guard** (`bin/keel-house-guard`, every house's PreToolUse Bash hook) reads a
  command's push destinations first (`flowfence.targets`, no board asked for a command that
  pushes nothing), then `kb flowinfo`, and refuses a destination that is a shared branch, on
  any stage. Its refusal names `kb flowpush`. What it cannot read, or what changes where a push
  goes, counts as every branch, so it is refused:
  - a push inside `sh -c` or `$(...)` is read through; one in a script's argv is not, and counts;
  - a refspec the shell builds (`$T`, a backtick, `$(...)`) or a glob refspec;
  - git run through a variable (`$G push`, a backtick lookup `` `which git` push ``, c-723)
    or a function's `"$@"`, and a push fed by `xargs`: any `push` word beside a word the
    shell fills in, whatever program it belongs to (so a house's board push names its card
    literally, as its brief does);
  - an alias that pushes (`-c alias.*=...push...`, or one in the git config), and a `git config`
    write (any `-f`, or the `set` form) of an alias that pushes or of `remote.*.push`;
  - `-c remote.*.push` or `push.default`, a `git config` write of either, a remote with a `push`
    refspec (which git applies to any push to it, refspec or not), and a `GIT_CONFIG_*` env or
    `xargs` on any git command that is not one of the commands that never push (`NO_PUSH`),
    since either may define or name an alias.

  Commands are split on `;`, `&`, `|` and newlines outside quotes, so a quoted command is read
  through as one.

  A command that pushes nothing reads as nothing, whatever runs it: `xargs git add`, a
  `GIT_CONFIG_*` commit, a config read or another setting, a note that says "git-push".

  **Its boundary.** The guard fences an honest house's shell: it reads what a command says.
  It is not a sandbox, and a program written to hide a push (a script file that pushes, say)
  is beyond what reading a command line can see. The hard boundary for a shared branch is the
  code host's own branch permissions, which are the team's to set.
- **`kb flowpush <id> <branch> [--pr <branch>]`** is the one way through. It is the card's own
  house's (`KEEL_CARD` is the card) or yours. It refuses unless your grant (`options.flow_move`)
  names a move that is still yours in the flow, the card is at one of its stages, and the move's
  and the grant's `pushes` both name `<branch>`. It pushes `HEAD:refs/heads/<name>` from the
  current worktree to the space's remote (`[spaces.<name>] remote`, `origin` unless it says;
  `kb flowinfo` carries the name, c-665), never forced, and notes the push on the card at once: a push that is not a fast-forward is refused by git and
  said, and the grant stays for the retry until the card moves stage. With `--pr` the move's
  `opens` must name the target too, and the space's pack opens the pull request
  (`pr <id> --flow <branch> --to <target> --dir <worktree>`, the worktree naming the repo, so a
  card in several repos opens each where its branch was pushed). A pull request that fails is
  noted beside the push that landed.
- `kb flowpush` is a command line the guard's push pattern and the shipping deny entries do
  not match, so a move you make works at shipping too, where every raw push is refused.

## The work pack's flow (c-641)

`<install>/packs/work/flow.toml`, the work space's default until it adopts its own:

| Branch | Label | Kind |
|---|---|---|
| card | card branch | card |
| base | `{base}` (the staging branch or master, `options.base`) | base |
| dev | dev_review | environment |
| master | master | trunk |
| pick | `{branch}-master` | work |

The house's draft pull request, your Approve and Ship, and a teammate's review and merge are
drawn as they already happen. Your two moves (the file spells them `by = "him"`, which still loads):

- **Merge to dev review** (`to-dev`, building, review and shipping, pushes `dev`): the house
  merges its LOCAL branch (which at shipping holds commits not pushed yet) into a local
  branch from `origin/dev_review`, resolves conflicts itself, and `kb flowpush <id> dev`. The pull request to the base goes on as before.
- **Early merge to master** (`early-master`, review and shipping, only for a card based on
  the staging branch (the move's `bases`), pushes `pick`, opens `master`): the house cuts `{branch}-master` from
  `origin/master`, cherry-picks the card's own commits from its local branch (`-x`, merges
  left out), resolves conflicts, and
  `kb flowpush <id> pick --pr master`. The pull request is opened ready (your move asked for it)
  and recorded as `options.flow_prs.master`.
