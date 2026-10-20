# Plans on the deck

How every new plan and outcome is written, read and answered (shipped 2026-09-24, on in
both spaces: `[keel] plan_pages`). A house writes its plan (or its outcome record) as
markdown plus a closed set of fenced blocks; the deck parses it, draws it in the space's
theme at `/plan/<card>` and `/outcome/<card>`, and the user answers it in place. It replaced
lavish's renderer and runtime for plans, keeping lavish's AUTHORING discipline as a contract
that a lint enforces. The format is `docs/plan-format.md` (a house's brief carries its card);
this page is how it works. A card whose plan is still a lavish page, or markdown without
frontmatter, keeps opening the way it did (P4-2, below).

## Why it exists

Two plan dialects had two quality floors. A lavish plan asked tappable questions only when
the house remembered to load the skill, and the answers lived in lavish's own state file,
collected by a bounded poll on resume (P1). A markdown plan asked nothing tappable at all.
The earlier replacement (c-088) failed on LOOKS against a lavish surface the user liked, and the
one after it (c-089) lost the skill's discipline because nothing made a house use it (c-208,
c-212). So this has three halves, each a mechanism:

- **The format** is closed: a house writes content, never HTML, and the deck owns every
  pixel, in the deck's own tokens.
- **The contract** is a lint: `kb lint`, and `kb stage` refuses a plan in the format that
  breaks it (every decision has options with costs and one recommendation with a why, every
  open question carries a recommendation, a repo card shows its flow, refs resolve: a plan's at its `at:`, an outcome's at the card's branch tip).
  The flow is a BOARD embedded by id (C4, round 2): the house pushes it with `keel board
  push --card <id>` and the plan names `b-NNN`, so the board page lists it under the card
  and one fix shows in both places. Every embedded id must resolve: the deck and `kb`
  read the boards on this machine (`plangate.board_resolver`). A
  board THE USER DELETED is the exception (lane BD): the finding is a warning, not an error, so a
  card at its gate is not refused by that deletion, and the page draws a small "Board deleted"
  placeholder with who deleted it and Restore instead of the drawing. The page's tag carries
  the board trash's stamp, so a delete or a restore is seen on its next load.
- **The answers** are card events: one store, no poll, delivered by the gate verbs that
  already exist.

## What a house is told

With `[keel] plan_pages` on (the shipped example has it on; false is the one line back to the plan
styles), every house's brief carries a section of its own, "How you write the plan and the
outcome" (`keel/planbrief.py`), in both spaces and in both shapes that have a shell (a repo
card and a fenced errand; a house with no shell writes no plan). It carries the FORMAT CARD,
generated from the parser and the lint (`keel/plancard.py`): the frontmatter, the sections
in the lint's order, one line per fenced kind in `planblocks.KINDS`, the markdown it reads,
and one line per rule a mechanism holds. `tests/test_plancard.py` fails when a kind, a
section or an enforced rule has no line, and `docs/plan-format.md` embeds the same card in a
`plancard` block (`python3 -m keel.plancard --write` rewrites it). Around the card the
section says: `kb lint` before a stage; flows are boards the house pushes (`keel board list
--card` first, to extend or reuse one, then `keel board push --card <id> --new --file
<ops>`, one board per `board` line) and embeds by id, as rich as its context allows; the user's
round arrives through Approve and Send back, with nothing to poll; and an Ask is answered
with `kb reply`, the plan unrevised and the card unmoved. The lavish lines are left out.
**An outcome explains what was actually done** (c-719): the section says, and the card and
`docs/plan-format.md` repeat, that the five sections are a short frame and that the house
explains the work in sections of its own between them, in prose and tables, with a board or
diagram only where it explains better than prose and a sentence or two saying what each
shows. It asks for no board beyond the ones the brief already names (a code card's redrawn
flow and Code flow, a research card's one findings board), on the owner's word that too many
boards are a nuisance; no lint rule asks for one. The record a card starts with
(`planbrief.context_skeleton`) says the same in a markdown comment (`SKELETON_NOTE`), which
the parser drops (`planformat.uncomment`: a `<!--` that opens a line outside a fenced block,
through its `-->` on that line or a later one; text after `-->` is kept; a `<!--` that never
closes is drawn as text and the lint warns, an error in a card's record at `kb stage
review` and the approval check, `planlint.strict_record`, r2.F8; the work pack's PR body
escapes it as `&lt;!--`, so the code host shows it as the page does), so a house that leaves it in shows the
user nothing. Every reader of a record takes comments out by the same rule, so the page, the
pane (`deckstate.section`, `deckstate.pr_body`, through `planformat.strip_comments`) and the
pull request (the work pack's `pulls.pr_body_section`) read the same words.
In a space whose pack stacks (c-718, `planbrief.stacking_block`), one more bullet, "Stacked
or independent", every part of it conditional (r2.F9). Its split half applies ONLY IF the
plan splits the card, and gives the row's shape with no example row: each slice that waits for
another gets `s<n>: <its exact title> (after <the slice it waits for>) | stacked | <why>`, so
the owner's Approve gives every slice its answer before the house's `kb split` makes it. It
also asks a slice that needs fewer repos than the card names to say which in the plan, and
the house's `kb split` to state them (`|repo=<key[,key]>`, c-771). Its
second half is there only when cards already wait for the one being planned, names them, id
and title (r1.F14), and gives their rows. All rows go in ONE ```` ```batch stack ```` block
(`choices: stacked, independent`), and the breakdown is shown once on a board, only if the
plan splits or cards wait, drawn on a board the plan already embeds when it fits there, else
one small board of its own.
Nothing else asks for a board, and no lint rule holds the block. The owner answers each row in
Decide like any batch row, and `kb approve <id> plan` records the round ([cards and
gates](10-cards-and-gates.md), "Stacked or independent").
The record starts as an outcome in the format, so the review stage lints it; the work
adapter's brief puts the PR body in a ```` ````copy PR body ```` block, which its `pr` and the
pane both read whole.

## The parts

| Part | What it does |
|---|---|
| `keel/planformat.py` | the document: frontmatter, sections (named by their heading words), paragraphs, lists, task lists, tables with tone chips, callouts, pictures, and the fenced blocks; every block gets a stable id |
| `keel/planblocks.py` | one small grammar per fenced kind: `decision`, `batch`, `options`, `compare`, `questions`, `steps`, `stats`, `copy`, `details`, `diff`, `mermaid`, `board`, `finding`, and code with a path and a why; a batch row id alone may hold a dot (`ROW`, up to `ROW_MAX` 96, kept as written: a two-repo card's reply handle `webapp-react.c21`, c-580), every other key is `KV`'s |
| `keel/planfinding.py` | the `finding` block (lane FC): one review finding whole, its severity, member, `at: path:line`, claim, evidence, the verifier's word (disputed with both sides), suggestion, the drafted comment (its paragraphs kept) and the choice with its reason |
| `keel/planinline.py` | a line of markdown as typed spans, and the references it names (`c-NNN`, `sc-NNNNN`, `PR #N`, `path:line`) |
| `keel/planmermaid.py` | a flowchart, a sequence or a state diagram TRANSLATED into board ops, so the board's own renderer draws it (B2 keeps a third-party parser off this origin) |
| `keel/planlint.py` | the contract, C1 to C33, and `ENFORCED`, which says per rule whether a mechanism holds it; C26 holds an outcome to its five sections and a research or report outcome (`kind: research` or `report`, c-719) to its four, `RESEARCH_SECTIONS`: Findings, What it means, What is next, Evidence; C27 is the pipeline's risk step, a Risk section naming low, medium or high in the outcome of a card started with the pipeline; C7's refs resolve against every worktree of a cross-repo card (`card_roots`, `card_resolver`, SH-12) |
| `keel/planreview.py` | the review kind's rules, C28 to C32: a review card's outcome opens with its orientation (a paragraph, the code path as a board by id, a reading order of `path:line`s), its findings are ONE `finding` block each (and every finding that survived the verifier is one), it has exactly one `decision verdict` (comment, changes, approve, `other: no`), a re-review raises nothing the user posted or dropped on lines that did not change, and a feature card's findings name their member and resolve in its worktree. `items` reads the findings in either shape: the old batch with `copy comment` blocks stays readable for an outcome already at the user's gate (a warning there, `legacy`), and is refused for a new one |
| `keel/planoutcome.py` | C33 (c-602): an outcome that ships a change embeds a board pushed after the user's plan approval (`approved_at`) and a numbered reading order of `path:line`s under Why this shape (C28's `planreview.reading_order`); a warning per board carried over from the plan, and the page's `carried` tag (`mark_carried`) |
| `keel/outcomeboards.py` | `bin/keel-outcome-boards`: the C33 backfill for outcomes already at the user's gate (below) |
| `keel/planexcerpt.py` | a finding's code AT RENDER (lane FC): the lines around its `at:` read from the card's worktree at HEAD, four either side, a feature finding's from its member's worktree (`options.review_worktrees`); by the route here (`planroute`). The house never writes code into a review, so what the user reads cannot drift from where the comment lands |
| `keel/plangate.py` | the kb side: `kb lint` (reading the card's own checkout, `card_root`, r-23), and the refusal on `kb stage` for a plan or record in the format, the pre-gate pipeline's checks at `kb stage review` (`keel/review/stagecheck.py`), and a `--plan` or `plan_ref=` made absolute before it is stored (`absolute_plan_ref`, c-574; see [cards and gates](10-cards-and-gates.md), "Where the record lives") |
| `keel/planstate.py` | the user's marks: what a round is, and the ONE text a send composes |
| `keel/planroute.py` | `GET /api/plan/<id>[?doc=outcome|context|files|file&name=]`: the document, the lint, the round, board lines and file tokens in one answer; `PLAN_PAGE` is `/plan/<id>`, `/outcome/<id>` and the viewer's other pages, `FILE_PAGE` is `/file/<id>/<name>`; its helpers `format_docs`, `outcome_path` and `local_plan` say which documents a card has and where they are |
| `keel/cardfiles.py` | the markdown files a card wrote beyond its plan and record (c-719): `listed` for the Files page and the card pane, `resolve` for one file, only from inside the card's folder, `output_page` and `link_page` for a named output and an outcome's link to one |
| `app/plan.html`, `app/ui.planpage.js` | the pages' own shell and boot: the deck's core and the plan's renderers, and none of the deck's chrome (no rail, header, dock, card list or `/api/state` load). The board's drawing (`ui.boardlayout`, `ui.board`, `ui.planlook`, `ui.plandiagram`, about 43 KB compressed) is fetched by `ui.planblocks.js` when the first diagram needs it (P4-7), and ELK by the board's code when the first graph is laid out, so a document without a diagram loads 9 requests and 92 KB instead of 13 and 134 KB |
| `keel/planactions.py` | the `plan.send` verb: compose, then hand to Approve or Send back; refused at a gate the receipt says was answered, and Approve again after a refused landing clears that refusal's block first |
| `keel/receipt.py` | the RECEIPT a gate leaves once it is answered (c-537): who answered and when, from the card's events, and what is happening now, from its own state; `answerable` says whether the page may draw the buttons |
| `app/ui.receipt.js` | draws the receipt, the same on the send panel and in the card Inspector (the deck's and the Console's) |
| `keel/planask.py` | the `plan.ask` verb (Ask, P2-9): the user's question sent to the house at once (told in its session, or held while it works, c-598), without sending the plan back; the house answers with `kb reply` |
| `app/ui.plan.js` | the route, the slim header, the round, notes (the margin button, Add note beside a selection, pinned notes), Send |
| `app/ui.planblocks.js` | one renderer per block kind, every node built with `textContent` |
| `app/ui.plancode.js` | code in colour (lane FC, FC-3): every `code`, `diff` and copy block and a finding's lines, coloured by highlight.js (vendored in `app/vendor/highlight/`, imported only when a page has code), its token tree walked into text nodes, never its HTML; six colours on the deck's tokens (`.hl-*` in `app/ui.plan.css`), each 4.5:1 or better on the code background, the diff tints and a marked line in both palettes; a diff keeps its added and removed tints under the colours |
| `app/ui.planfinding.js` | a review finding as ONE card (lane FC, FC-2): the head (severity, member, `path:line` linked to its pull request, claim), the code with its lines marked, the why, the comment in a field the user rewrites (Keep these words is the RC-3 edit mark), the choice; two columns on the desk, stacked on the phone with a low finding folded to its head |
| `app/ui.plandiagram.js` | a diagram in a plan, drawn once by the board's functions (`K.boardDraw` in `app/ui.board.js`), fitted to the column, and opened full screen on a tap |
| `app/ui.planlook.js` | the plan's LOOK on the board's drawing (`model.look = 'plan'`): wrapped labels, 13px, an icon only where the source names one, and the layout chosen for the column (`chooseForColumn`) |
| `app/ui.plan.css` | the page's styles, from the deck's tokens |

## One store: the user's marks

Every tap on the page is written at once as a `mark` event on the card, through `kb mark`
with the user's token. The data is one of four shapes (`planstate.check_mark`): an `answer` (an
option, a batch row's choice, a reply to an open question, or the user's own words), a `comment`
(pinned to a block id, with the words the user selected as a separate `quote`), a `drop` (a note
taken back), and `sent` (a round closed). A mark is the user's alone: `Board.mark` refuses every
actor but `human`, because the composed text quotes marks as the user's words and a house writing
one would be putting words in the user's mouth. `mark` is one of the deck's kb verbs and is kept
out of a house's brief (`prompts.FORBIDDEN_VERBS`).

**Edit wording (RC-3).** A batch row whose choice is `edit` (a reply in a batch)
opens a field under the row, prefilled with the house's draft for it (the `copy reply <row>`
block) or with the user's words once some are kept; a review finding (lane FC) always shows its
comment in a field, opened with its `comment:` draft, and its pick is a row mark on its own
block (`block` and `row` both the finding's id).
Picking edit keeps the words the field opens with, and "Keep these words" keeps what the user
typed; either is the row's `answer` mark carrying `choice: edit` and the user's words as `other`,
so the round state has an `edits` map beside `rows` (`planstate.state_of`), the newest mark
winning. Approve sends those words in place of the draft, and a review card's Approve refuses an
edit left empty. A shipping card's replies are not a batch on a page any more (c-600): they
are the standing batch on the card, marked the same way under `doc: shipping`
([cards and gates](10-cards-and-gates.md), "Review at shipping").

A ROUND is every mark since the last `sent` for that document. The page shows the round
before the write returns and reloads when the stream says `card <id>`, so another screen
follows without a poll.

## Ask: a question cleared without sending the plan back (P2-9)

Beside Note, the note sheet (and the selection's buttons) offer **Ask the house**. A note
waits for the user's Send; a question goes NOW. `plan.ask {id, doc, block, quote, text}` (a gate
verb, the page's alone) records it as an `ask` mark on the card and resumes the house
with `prompts.plan_ask`: answer this, do NOT revise the
plan file, do NOT move the card, reply with `kb reply <card> --ask <id> --text "..."`. The
house's `kb reply` is a `reply` event on the card tied to the ask's event id
(`Board.reply`): refused to anything but the card's OWN house (actor `house` and
`KEEL_CARD` naming the card), to an id that is not the user's question, and to a question already
answered. The stream's `card <id>` reloads the page, which pins the answer under the
question on its block and in the round's list. A house's `kb reply` writes the board from
its own process, so the deck publishes nothing for it: the sweep of a stream opened with
`?plan=<card>` keeps that card's `card_rev` and, whenever the board's stamp moves, says
`card <id> <rev>` when it changed (`Handler.plan_card_rev`, c-579). The board's kb checks
the replier's `KEEL_CARD`. The card stays at its gate, the plan file is
untouched, and the user's other answers and notes stay pending for the final Send (an ask is not
part of what Send composes). It replaces Send back and stay on these pages.
An Ask on the OUTCOME page says outcome to the house (`prompts.plan_ask` with the document:
"a question about your outcome", the record and the code left as they are), and the turn
that answers it is never sent back to building: the Stop hook's review-stamp check holds
only the turn that staged review itself (`review.gate.staged_this_turn`, c-600: without it
an outcome Ask moves the card from review to building).

**An idle house is TOLD, in its own session** (c-598, `keel/tellhouse.py`): the question
reaches it as a message, its session id and app link unchanged, rather than a resumed copy;
an exited house is resumed ([houses](20-houses.md), "The user's taps, told in place"). **A working
house is never interrupted.** While an earlier question is still open the house is taken to
be answering it, so the new one is recorded and not sent, and `kb reply` prints the next open
question with the command to answer it (asks QUEUE). With no earlier question open, the ask
is HELD (`planask.working` says `hold`): a `resume` relay for this machine, told to it
when its turn ends. A session open in the user's terminal is still refused with the reason. A house
that ended its turn with questions still open is told every open question, in order.

**Side answers are not built** (c-598). The probe found `claude -p --resume <id>
--fork-session --no-session-persistence` safe on a live session, idle or mid-turn: it answers
from the house's context under a new id, leaves the original's transcript untouched, and
runs none of its hooks. It was not wired in, because an answer is pinned under the user's question
only by the card's own house (`Board.reply`), a side session would need an author the board
trusts, and a busy house at an open gate is the case asks already queue.

## An outcome's boards: redrawn at the built head, and a Code flow board (C33, c-602)

A plan's board is drawn before the code exists, and the brief allowed it lean ("the full
walk comes with the outcome"), but nothing asked the outcome for it: without this rule an outcome
re-embeds the plan's boards as they were (c-573). The outcome should at least
upgrade them, and add a code flow board that helps the user read the code in a particular order.
c-272's b-009 is the model: a node per unit with its path, edges in call order labelled with
the call, numbered steps carrying one worked example with its code and the tests that pin it.

- **The brief** (`planbrief.OUTCOME_BOARDS`, in both spaces' plan section; one line in the
  work ENDING's Verify, `<install>/packs/work/pipeline.md` and `etc/pipeline-personal.md`): at
  Verify, ONE background subagent redraws every board the plan embeds (the same board,
  `keel board push --board <id>`, which REPLACES what it shows, c-604; the plan page
  stays pinned to the board as approved, `planroute.pin_board`) and pushes one `Code flow: <what>` board, then writes the board blocks and `### Read
  it in this order` (a numbered `path:line` per step) to `outcome-boards.md` in the card's
  directory, never into `context.md`, so two writers never edit the record at once. It needs
  only the built head, so it runs beside the full suite and costs nothing on the path to
  review; the house JOINS it before `kb stage review`, merges its text under Why this shape,
  and rechecks the lines on the final head after the review's fixes.
- **What is exempt**: the outcome's frontmatter `change: none` (a card with nothing to land,
  whose outcome is its record) is not held by C33, and `change: docs` (a docs-only change)
  needs the reading order but no board. **The claim is checked against the branch** (c-605,
  `planoutcome.claim_rules`): a house wrote `change: none` over a real code change and
  dodged the Code flow board. `none` exempts only when the card's branch has no commit over
  its base in any repo of the card, and `docs` only when every changed file is
  documentation (`planoutcome.is_doc`: a README or CHANGELOG anywhere, `.md`, `.rst` or
  `.adoc` under a `docs`, `doc` or `documentation` directory, `.txt` only there; never a
  requirements.txt, a CMakeLists.txt or a contract under `etc/`). Otherwise C33 applies in
  full, led by a finding that says the claim did not match. `planoutcome.branch_change`
  reads each worktree (`planlint.card_roots`) against ITS OWN base (`plangate.claim_base`:
  the repo's pull request base in `options.prs`, else `options.base`, else that repo's
  integration branch, else its main checkout's branch), and a count over the base is taken
  again after one fetch of that base, so a stale tracking ref never reads as the house's
  commits. A claim nothing could verify (no worktree here, a base that does not resolve)
  is NOT trusted: C33 applies and the finding says why (c-605 review). It runs at `kb stage
  review` and `kb lint`; the deck's own reading of the page does not check it.
- **The lint** (`keel/planoutcome.py`, run by `planlint.lint` for an outcome that `ships`,
  as C27 is): an error when no embedded board was pushed after the user's plan approval (the
  newest `approve` of the plan gate, else the FIRST move into building, so a card sent back
  from review does not call its first round's boards the plan's), and when Why this
  shape has no numbered list of `path:line`s; a warning per board last pushed at or before
  the approval. A board's push time is `boards.pushed_at` (its `last_push`, else when it was
  made: `updated` moves on open and close too), read through the same resolver as C4
  (`plangate.board_resolver(cfg).pushed`); a time nobody can read counts as fresh. The rule is an error
  at `kb stage review` from building and a WARNING once the outcome is written (review,
  shipping, done: `planoutcome.written`), so no card already at the user's gate turns red and
  Bosun's approval facts (`authority.outcome_facts`) are not refused by it.
- **The page** tags a board carried over unchanged: `planroute.payload` marks it `carried`
  and `app/ui.planblocks.js` draws "from the plan, not updated" in the board's head, beside
  Open board.
- **The backfill** is `bin/keel-outcome-boards` (`keel/outcomeboards.py`), built and not yet
  run: it picks each card a HOUSE built (`outcomeboards.housed`: not archived, not done, not
  Bosun's, so neither a personal Keel card nor any personal repo card in builder mode, which
  have no house and no outcome page) at review or shipping that ships a change, has a house session and
  an outcome in the format, and breaks C33 or has a plan board drawn before the approval that
  the outcome does not embed. It reads the documents where they live (`planroute.read`) and
  the boards and events here. Without `--run` it prints each card, why, and the prompt; with
  `--run` it records one `resume` relay per card for this machine, the way a held tap is, so
  the drain tells an idle house in its session, holds it while it works, and resumes an
  exited one: nothing is stopped. The relay is written with `kb relay --bulk`, so the pass
  never restarts a card's backlog clock (c-673). Each card asked carries `options.outcome_boards_sent`,
  and while its house has not ended a turn since (`outcomeboards.pending`), another `--run`
  skips it rather than queue the prompt twice; `--force` asks again. The prompt (`outcomeboards.PROMPT`) is board-only (no code,
  no commit, no push, the card not moved) and quotes `OUTCOME_BOARDS`, so a card fixed later
  is asked for exactly what a new one is told.

What it cannot judge: whether the Code flow board really walks the code in call order, or
whether its example is the right one. The lint holds that a board was drawn after the build
and that a reading order exists.

## A ref into a card's second repo (SH-12)

A cross-repo card has a worktree per repo, and its plan or outcome may cite a file that only
its second repo has. C7 resolves a `path:line` against EACH of them and passes it when any
one has the line (`planlint.card_resolver`; a ref none has says so "in any of the card's 2
worktrees"). The worktrees are the house's own checkout first, then what the card records:
`options.worktree` and `options.worktrees` (`{repo: path}`, written by the work adapter's cut
and by the shipping sync), and for a personal card `<id>-<repo>` beside its `<id>` worktree.
## Where C7 reads a ref (r-23)

A plan is read at the commit it names in `at:` (`GitResolver.pinned`), since it describes the
code before the change. An outcome is read at the card's branch tip (`GitResolver.tipped`,
`planlint.card_tips`): `options.branch`, else the branch or sha `output_ref` names
(`merging.named_branch`), else the builder's fetched copy of it (`refs/builder/<branch>`: its
branch is in its clone, never under the live checkout's `refs/heads`), else
`options.landing.sha` once the branch is deleted at landing.
Every checkout of the repo shares its refs, so the answer does not depend on which checkout
the lint runs in; a checkout that has none of them is read at HEAD as before, and a finding
names where it read (`does not resolve at keel/c-551-...`). A ref not on the branch still
refuses. The checkout itself is the card's own (`plangate.card_root`: its worktree, else its
primary repo's checkout) for `kb lint` without `--root`, `kb console plan` and Bosun's
approval facts (`authority.plan_facts`, `outcome_facts`), and the caller's cwd only when the
card has neither (c-551: `kb console plan <id> --outcome` run in the live
checkout on main would refuse a file the card's branch adds).

The one rule is used wherever C7 runs: `kb lint` and `kb stage` (`plangate.resolver_for`,
which `bin/keel-plan-install` goes through with the card's worktree as its root), and the
plan page (`planroute.resolver`).

## Counts where the user looks (P4-5)

A card at a gate whose document is in the format carries `plan_doc` on the state document,
and its row and its Attention row draw it: "4 decisions, 1 changed · 1 question · 2 notes ·
1 reply waiting · 1 ask open" and "contract holds" or "2 breaks". It is `keel/planfacts.py`,
in two halves. The DOCUMENT's half (in the format at all, its decisions with their
recommendations, its open questions, whether the lint holds) is the page's own parse and
lint, cached per file stamp (path, mtime, size) so a state build reads a plan once per
change; it is read where the file is. The ROUND's half (the user's notes, the
decisions the user changed, the Asks open and answered) is counted off the card's events here.
The row's lint leaves out the `path:line` check, which runs git per path: `kb stage` already
refused a plan whose refs did not resolve, and the page runs it whole.

## The viewer (c-644)

Every page of a card is drawn on this one shell, and each switches to all the others: the
plan (`/plan`), the outcome (`/outcome`) or the context (`/context`), the card's other
markdown files (`/files`, and each at `/file/<card>/<name>`, c-719), the review comments
(`/comments`, [a card's review comments](67-comments.md)) and CI (`/ci`, [a card's CI](66-ci.md)).

- **The tabs** (`K.docTabs`, `app/ui.plan.js`) lead each page's header: the card's pages in
  one fixed order, Plan, Outcome or Context, Files, Comments, CI (`planroute.PAGES`), the current
  one marked (`aria-current`, not a link) and every other a link. They scroll sideways on a
  phone. A card with one page has none. The order never moves with the stage: the stage only
  picks which page the pane's Pages button opens.
- **The pages a card has** are the payload's `docs`: `planroute.format_docs` (the plan and the
  outcome in the format, or `context` for a `context.md` that is not), then `planroute.more_pages` (CI, comments,
  and `files` once the card wrote a markdown file beyond its plan and record).
- **The context page** draws a `context.md` with no frontmatter as plain markdown: the same
  answer as the outcome (`/api/plan/<id>?doc=context`), with `doc_name: context`, no gate,
  no receipt, nothing answerable, no contract findings (the answer clears them and the page
  draws none), and no adapter links read. A note kept on it is the outcome's (`markDoc`):
  it is the same file. A record in the format is the Outcome page: asked as context, the
  answer is `{"redirect": "outcome"}` and the page replaces itself (the deck's
  `links.formats` is read at the live stages only, so View context on a done card may ask).
  The tabs never show both: Outcome and Context are one record, and `docTabs` keeps the one
  that is current, else Outcome.
- **The card's files** (c-719, `keel/cardfiles.py`): every `*.md` the card wrote in its folder,
  its own files first and then its folders' (three levels at most), each read through the SAME
  parser and block renderer as the plan and the outcome, so a board, a table, a callout, a
  mermaid diagram or a decision block draws as it does there. The plan and `context.md` are
  left out (they are Plan and Outcome), and so are hidden names, `told/` (Keel's record of
  what the user told the house) and a board's file folders (always downloads); a named
  output (`output_ref`) that is a markdown file in the folder is listed wherever it sits.
  `/files/<card>` lists them (name, size, when written); `/file/<card>/<name>` reads one with
  `?doc=file&name=<name>`, read only: no gate, no receipt, no contract findings, no notes and
  no selection popup. The Files tab is marked on a file's page and stays a link back to the
  list. **Only from inside the card's folder**: `cardfiles.resolve` refuses an absolute name,
  `..`, a hidden component, anything not markdown, a name under `told/` or a board's file
  folders (left out of the list and refused by name alike), anything a symlink resolves
  outside the folder, anything `artifacts.denied` calls a credential, and anything over the
  artifact cap, and the route answers 404 with why. After a link is followed the same rules
  run again on where it landed (r1.F2): a `notes.md` link inside the folder to `raw.json` or
  to a hidden file is refused, and the list leaves it out. The page sends a name, never a
  path. The list is read ONCE per request from the card's own row, so its named output
  counts (r1.F11), and its stamp (`cardfiles.stamp_of`: names, sizes, mtimes) is in the
  answer's ETag and the card detail's, because a house writes a file without a board event.
  A `/file/` page's tag adds `cardfiles.file_stamp`: a hash of the name (never the name, which
  may be anything but latin-1, r2.F5) and the file's own size and mtime, so an edit to a file
  the list does not hold, deeper than the walk, moves it too (r2.F7). `told/` and the board
  folders are refused in any case (`Told/`, r2.F6), and a file gone between the list and its
  stat is left out rather than failing the page (r2.F11).
  The state build asks the disk for a named output only when it is a local markdown name. An outcome's relative link to a card file opens it
  here (`planroute.decorate`, `cardfiles.link_page`); any other link keeps its artifact
  token. The plain dark page (`artifacts.markdown_html`) is what a token for a markdown file
  outside a card folder still serves.
- **The flow's moves** (`K.flowBar`) sit under the title on every page of the viewer: what
  the user may do to the card's branch now (`planroute.moves_of`: `flows.offered`, on a card with a
  session, as the pane's), in the groups the flow names, each the pane's own `flow.move`. The
  plan answer's ETag carries the flow files' stamps (`planroute.flow_stamp`), so an edited
  flow redraws them.

## Old plans keep working (P4-2)

`links.formats` says which of a card's two documents is in the format, and only those open
on `/plan/<card>` and `/outcome/<card>`. A plan that is a lavish `.html` keeps its live
surface (`plan_live`) and its phone layer; a markdown plan with no frontmatter keeps the
markdown pane (its artifact link). A `context.md` with no frontmatter is the viewer's
**Context** page since c-644 (below). Cards in flight at deploy therefore
open exactly as before, and a new card's record starts in the format. Nothing of lavish is
deleted in this round (LP-16 says when it goes).

## Putting a converted plan on a card that is already at a gate (P4-9)

A card at a gate when the plan pages ship keeps its lavish plan and markdown record (P4-2).
To give it the new pages, its documents are converted on a scratch deck and then installed
with `bin/keel-plan-install <card> --plan <plan.md> --context <context.md> --board
b-003=<flow-1.txt> ... --reuse b-001=b-006 ... [--root <worktree>] [--dry-run]`
(`keel/planinstall.py`), run where the card's files are. It refuses before changing
anything when an embedded id is neither given a line file nor one of the card's own boards,
or when the documents would not lint with the planned ids counted as resolved. Then it
pushes each line file with `keel board push --card <id> --new`, rewrites the documents'
board ids (and their `card:`) to what the store answered, runs `kb lint` on the result,
keeps the old files beside the new ones (`plan.html.lavish`, `context.md.pre-format`; a
plan outside the card's directory is left where it is), sets `plan_ref` to the new
`plan.md`, and writes one note. It never moves the card. The work adapter's `pr` reads the
PR body out of the outcome's copy block, and its `publish` reads nothing of the record, so
Approve outcome on such a card publishes as before.

## Send

`plan.send {id, mode, doc}` is a gate verb. The server reads the round, composes one text
(`planstate.compose`): every decision, each marked as the user's pick or as the recommendation
left standing, the batch rows the user changed, each open question's answer, then each note with
the block it is on and the selected words kept apart from what the user wrote (c-175 relayed the
selection in place of the user's words). Approve hands it to `approve` as `said`; Send back hands it
to `sendback` as the reason. Nothing new resumes a house. A `sent` mark then closes the round, and its decision ids are what C16
checks on the next revision. The text opens with the page it came from ("The user sent the
outcome back from the outcome page of c-N", `compose`'s `doc_name`, c-600).

**A send back needs the user's words** (c-600). With no note, no changed answer, no changed row
and no reply (`planstate.has_words`), `plan.send` refuses a send back ("a send back needs
your reason"), as the pane's Send back asks for one; the page draws the button disabled with
that line, and with words it confirms before it goes. Approve outcome on the page confirms
exactly as the pane's does ("This publishes it").

### Once it is answered: the receipt (c-537)

After Approve nothing used to say what happened, and the buttons came back once the command
went through: an outcome approve leaves the card at review while it lands, so the gate
still read open. Now the send panel becomes a RECEIPT, and the buttons show only while the
gate is really open.

`keel/receipt.py` decides, from the board alone. The ANSWER is the newest of these after the
gate last opened (the newest `stage` event into planning or review): an `approve` event for
the plan; a `land` relay (the user's queued tap or Bosun's checked approval) or a non-drain
`approve` for the outcome; the page's `sent` mark (a plan Send back leaves the card at
planning, so the mark is its only record); the user's move from review back to building. Its actor
is said as "you", "you, by voice" or "Bosun". What is happening NOW comes from the card:

| The answer | The card | The receipt says |
|---|---|---|
| plan approved | building, with a session | house resumed, building |
| plan sent back | planning | house resumed, revising the plan (until the house ends that turn: it revises in place and moves no stage, so its Stop hook opens the gate again) |
| outcome approved | a `land` relay pending | landing, queued for <host> |
| outcome approved | `options.landing` testing | landing, testing the merged tree on <host> |
| outcome approved | done, landed | landed on next at <sha>, goes live with the next deploy (said only for the repo's `[integration]` branch) |
| outcome approved | review, landing refused | refused: <the failed tests>, a link to `merged-tests.log`, and Approve again |
| either | blocked | blocked: <the first line> |

The payload of `/api/plan/<id>` carries `receipt` and `answerable` (open on the board, and
unanswered since it opened or its landing refused); `/api/card/<id>` carries the newer
gate's receipt for the Inspector. The page redraws on every `card <id>` event, which is how
landing becomes landed in front of the user. `plan.send` holds the same line: a second send at an
answered gate is refused (a stale tab), and Approve again runs `kb unblock --expect <the
refusal's block>` before it approves, so no other block is ever cleared by it, and puts
that block back if the approve then fails. The red "no
gate open" line is gone; a document with no gate and no answer says where the card is in
one quiet line. A plan Send back from the deck or by voice writes only a note, so the
receipt does not see it and that gate keeps its buttons.

## The page

`/plan/<card>` and `/outcome/<card>` are pages of their own (P2-5), not a view inside the
deck: `app/plan.html` loads the deck's core, the board's drawing and the plan's renderers,
and `app/ui.planpage.js` boots them with no rail, no header, no dock and no card list. The
DOCUMENT scrolls. Round 1's `/plan/<card>?doc=outcome` still opens the outcome and is
rewritten to its own path. The page wears its card's space palette without changing the
deck's remembered one. `?pane=decide|read` picks the phone's pane.

- **The tabs** (c-644, "The viewer" below) lead the header.
- **The header** is slim: the card id (a link back to the card in the deck), its space,
  which document this is, on an
  outcome from the user's gate on a link to each of the card's pull requests (`card.pulls`, the
  adapter's `links.prs` read once with the unpublished line, `deckstate.adapter_links_of`,
  c-565), the gate, the contract chip, and the frontmatter's meta line.
- **The phone** opens on **Decide** when a gate is open and the plan asks something: every
  decision with its recommendation selected, the batch rows, the open questions, the user's notes,
  and Send. **Read all** is the whole document. One scroll axis; a wide table scrolls
  sideways in its own box.
- **Many decisions on the phone** (P4-4): over eight (`K.plan.COMPACT_OVER`, counting batch
  rows), Decide draws each decision and batch as ONE 44px row: what it asks (two lines at
  most), where it stands ("recommended: <label>", "yours: <label>", or "n of m changed"),
  a `changed` marker in the accent when the user moved it, and the user's notes on it. A tap opens that
  decision's full card in place, with Fold under it. The questions stay whole, and there is
  one Send as before; a row never opened is its recommendation left standing. The voice
  plan's Decide went from 19346px to 2566px at 390x844. The desk draws everything whole.
- **The desk** shows the document in a reading column (at most 760px) and, beside it, a
  sticky rail: every decision on one line with where it stands, Send, and the user's notes.
- **No panel behind it** (P2-3): round 1 drew the document inside the deck's `.panel`, whose
  fill and border were sized to the first viewport (`.body>.panel.grow`) while the document
  scrolled on past it, so a grey square stopped at the bottom of the first screen. The page
  has no panel; the canvas is its background all the way down.
- **Notes** (P2-6) need no instructions: every block carries a note button in its margin
  (on hover on the desk, always there but quiet on the phone), selecting words inside a
  block puts "+ Add note" right below them, and Note on the whole plan sits in the round.
  A one-line hint says so at the top of Read until the user taps Got it (kept in the browser).
  Every note is pinned under its block and listed in the round with a jump to it, with Edit
  (the new note, then the old one's `drop`) and Remove (a `drop`) until Send closes the round.
- **The contract** is a chip under the title: "contract holds", or the count of breaks, which
  opens the list; a finding also shows under the block it is about, and a `path:line` that
  does not resolve is drawn in the crit colour.
- **Diagrams** are the board's own boxes and edges, drawn in the plan's look (P2-1). The
  plan passes the look on the model and the board's drawing asks `app/ui.planlook.js` for
  a node's size, its paint and an edge label's; a model with no look (every board on the
  board page) never asks, so the board page is unchanged. In the look a label WRAPS onto as
  many lines as it needs and the box is sized to it (no ellipsis; a path breaks after a
  `/`, `_` or `.`), labels are 13px and edge labels 11px, and an icon is drawn only where
  the source names one: a mermaid diagram gets none, and the board fallback `box` is none.
  The layout is chosen for the COLUMN: four shapes are laid out (as written, folded into
  rows at two heights, and down); the ones readable at a 10px label (a 0.77 floor) come
  first, of those the ones within 12 points of the cheapest readability cost, and of those
  the shortest drawn. So a long chain on a wide column is folded into rows, and a grouped
  board that only reads down stays down. It is drawn at the column's width, never above
  natural size; below the floor it keeps the floor and scrolls sideways in its own frame,
  with a fade on the side there is more of and a line saying so. A tap opens it whole:
  an embedded board opens the board's own full screen view (`/board/<id>?full=1`), an
  inline diagram a layer drawn by the board's own stage (`K.boardDraw.drawGraph`) with
  pan, pinch and Fit.
- **One button per diagram** (R3-1): an embedded board shows only Open board (a link to
  `/board/<id>?full=1`, the same place a tap on its drawing goes), and an inline diagram
  (mermaid or inline board lines) shows only Full screen (the in-page layer).
- **A review finding is one card** (lane FC): what the user decides about one finding in one
  place, where lane RC spread it over a batch row, a copy block and a Snippets section. The
  code is the server's, read from the worktree at HEAD when the page is asked for
  (`keel/planexcerpt.py`), four lines either side with the finding's own lines under an
  accent bar, so the house never writes code and it cannot drift from where the comment
  lands. The comment is a field opened with the draft; Keep these words is the finding's
  edit mark, which Approve posts at the line in place of the draft. On the desk (900 and
  up) the card is two columns, code and why left, comment and choice right, and a review's
  reading column widens to 1040px; on the phone it is stacked, the code in a frame that
  scrolls sideways, the why folded, and a low finding starts folded to its head. Decide and
  the desk's round list each finding as one decision. An outcome still in the old shape
  draws as it did.
- **Code is in colour** (lane FC): every code block, diff and finding the plan and outcome
  pages draw. highlight.js is fetched the first time a page draws code in a language it has
  (python, javascript with JSX, sql, yaml, json, bash), not on the page's first load, and
  never on a page without code; until it is in, the lines are drawn plain.
- **An embedded board keeps its walk** (P2-2): under its drawing, "What hangs on this
  board" (counted: steps, notes, tables) opens the board's own outline (`K.boardDraw.
  outlineView`, the board page's Outline renderer).

The card pane's Open plan opens `/plan/<card>` for a markdown plan, and View context opens
`/outcome/<card>`, both in a new tab. The event stream takes
`?plan=<id>` and says `plan <id> <stamp>` when the plan FILE changes, because a house
rewriting its plan moves no board event.

## What is left of lavish

Nothing of lavish is deleted yet: the proxy, the phone layer, `plan_live`, the P1 poll and
Send back and stay stay while any open card still has a lavish plan. Decision LP-16 lists
what goes, and when.
