# The plan format (v1)

A plan, or an outcome record, is ONE markdown file with a few fenced blocks. The deck draws
it in the space's theme (`/plan/<card>`), the user answers it in place, and `kb lint` holds it to
the contract before a gate opens. You write content; the deck owns every pixel. Never write
HTML, CSS or a script: they would be shown as text.

This file is the whole spec. A house's brief carries the short form, the card below, which
is generated from the parser and the lint (`keel/plancard.py`) so it cannot drift from them.
Every new plan and outcome, in both spaces, is written in this format while `[keel]
plan_pages` is on (it ships on); a plan already written as a lavish page or as markdown
without frontmatter keeps opening the way it always did.

## The card

```plancard
Plan format v1, card v1: ONE markdown file, frontmatter first, a few fenced blocks. Never HTML: the deck draws every pixel.

---
kind: plan        (or outcome; context.md is always an outcome, research on a research
                  card, or review on a review card)
card: c-NNN
title: one line
repo: <name>      any other key (branch, base, a ticket) is a meta line
at: <sha>         a plan: the commit it was planned against (`git rev-parse HEAD`, one
                  per repo, comma separated); its path:line refs resolve there
---

A plan: `# <title>`, a summary paragraph, then `## ` sections in this order: Goal, Now, Target, Proposal, Decisions, Risks, Steps, Proof, Out of scope, and optionally Open questions. Steps and Proof are for a repo card. A compare block may stand in for Now and Target.
An outcome (context.md): Where it stands, What is next, Why this shape, Open questions, Evidence, then Risk for a change that ships (low, medium or high, and why), and PR body where there is one (the body in a ```copy block, one per change). A finished change also says, as `###` under Why this shape, What changed from the plan and Review findings (what review found and what was done), and may end with Links. The five are a short frame: an outcome explains what was actually done in sections of your own between them, in prose and tables, with a board or diagram only where it explains better than prose and a sentence or two saying what it shows. A change that ships also redraws the plan's boards at the built head, adds ONE `Code flow: <what>` board, and under Why this shape gives `### Read it in this order`, a numbered list of `path:line`s.
A research outcome (a research card's context.md, `kind: research`; a `kind: report` is held the same): Findings, What it means, What is next, Evidence. It IS the research: the findings themselves, explained, in this one file, with no separate report file and no link to one; no Risk, no PR body.
A review (a review card's context.md, `kind: review`): the summary, then Orientation, Review findings, Verdict: one ```finding block per finding, its code drawn from the worktree by the deck (no Snippets).

Fenced blocks (the fence's language is the kind, the rest of its line the id or title, the body is `key: value` lines; an indented line belongs to the one above):
  decision <id>                q:, why:, 2 to 4 `option <id>: <label>` each with indented `gets:` and `cost:`, `rec: <option id>`, `because:`, optional `other: no`, `after: <decision id>`
  batch <id>                   q:, `choices: a, b, c`, then one row per item: `<row id>: <text> | <recommended choice> | <why>`
  options <id>                 `option <id>: <label>` with indented summary:, pro:, con:; `rec: <id>`; `decision: <id>` it feeds
  compare <title>              `left: Today`, `right: After`, rows `aspect | left | right` (aspect `image` takes two picture paths)
  questions                    `q:` then `rec:` (and `why:`) per question; same as a list under Open questions with `Recommend:` in each item
  steps <title>                one per line: `[todo|doing|done|blocked] Title | detail`
  stats                        one to six lines `label | value | sub | good|warn|bad|accent`
  copy <title>                 text kept exactly: a PR body, a commit message
  diff <path> | why            a unified diff
  mermaid <title>              flowchart, sequenceDiagram or stateDiagram-v2, at most 12 nodes: a SMALL picture beside the flow, never the flow
  board <title>                ONE line, the id `keel board push` printed (b-NNN): the flow
  finding <id>                 a review finding, whole: `severity: critical|high|medium|low`, `member: <repo>#<n>` (a feature), `at: path:line`, claim:, evidence:, `verifier: kept|unverified|disputed` (disputed: indented for: and against:), suggestion:, `comment:` (indented lines, posted as written), `choice: post|edit|drop`, because:
  details <summary>            markdown folded away: long evidence, logs
  <lang> <path[:lines]> | why  a snippet; the path and the why are required

A board's steps: Write each step as one or two plain sentences meant to be read in order, like a walk: what happens here and why it matters, not the node's label said again.

Markdown: lists (two levels), `- [ ]` tasks, GFM tables (a caption line above; a cell may open with [ok], [warn] or [bad]), callouts `> [!tone] Title` with tone info|warn|error|success|settled, pictures `![caption](assets/x.png){phone|desktop|wide}`. c-NNN, path/to/file.py:40, and the card's space's ticket and change refs link themselves.

What `kb lint` and `kb stage` refuse:
  C1   a summary paragraph comes first, at most 90 words
  C2   Goal, Now and Target present, and every section in order
  C3   a compare names both sides and every row fills both
  C4   a repo card embeds its flow as a board BY ID; every embedded id resolves
  C7   every `path:line` exists at HEAD of your worktree (any of them, for a cross-repo card; a plan's at its `at:`, an outcome's at the card's branch tip); a dependency's (node_modules/, site-packages/) is not checked
  C8   a code block carries `| why`, and a path unless it is a shell
  C9   Proposal is there and says something
  C11  a decision block, a `> [!settled]` callout for one the user answered, or `None: <why>` under Decisions; 2 or more options, each with a cost
  C12  every decision has `rec:` naming an option and `because:`; every open question a recommendation
  C14  `after:` names a decision on this plan
  C16  a decision the user answered last round is folded in and its block taken out
  C17  Risks lists one, or `None: <why>`
  C18  a repo card's Steps and Proof are there and filled
  C19  Out of scope is there and filled
  C20  the line above a table says what its rows prove
  C21  no paragraph over 180 words (a warning)
  C24  no em-dashes anywhere
  C26  an outcome has its sections (a research or report outcome its four), and Evidence names an artifact
  C27  an outcome that ships a change has `## Risk`: low, medium or high, and why
  C28  a review opens with Orientation: what it does, the code path as a board by id, a reading order of `path:line`s
  C29  a review's Findings is one ```finding block per finding, each with a valid severity, `at: path:line`, a claim, a `comment:` draft and a `choice:`
  C30  a review has exactly one ```decision verdict (comment, changes, approve) with `other: no`
  C31  a re-review raises nothing the user posted or dropped last round on lines that did not change
  C32  a feature review names each finding's `member:` (its path:line resolves there) and has ONE ```decision verdict-<repo>-<number> per member
  C33  an outcome that ships a change embeds a board pushed after the plan was approved (the plan's boards redrawn, one Code flow board) and a numbered reading order of `path:line`s under Why this shape; a board left as the plan drew it is a warning; frontmatter `change: none` (nothing to land) is exempt, `change: docs` needs only the reading order

The whole spec, with examples: $KEEL_HOME/docs/plan-format.md
```

## The file

```text
---
kind: plan              plan | outcome | research | report | pr | review
card: c-123
title: One line saying what this plan does
repo: keel              any other key: shown as a meta line (branch, story, pr, base)
at: 3f2a9c1e07          a plan only: the commit(s) it was planned against, one per repo,
                        comma separated. Its path:line refs (C7) resolve at that commit,
                        so the Now section's lines still point at the code the change
                        replaced; a checkout that has none of them is read at HEAD.
---
# c-123 One line saying what this plan does

The summary: what the user is being asked to decide, in two or three sentences (at most 90 words).
This paragraph comes first, before any section.

## Goal
## Now
## Target
## Proposal
## Decisions
## Risks
## Steps
## Proof
## Out of scope
## Open questions        (optional, see below)
```

The frontmatter is what marks a file as this format: a `.md` plan WITHOUT it is the old
markdown flow and is neither linted nor refused. Sections are recognised by their heading
words (for example "Now" also answers to "Current state" and "Where things stand", "Proof"
to "Tests" and "Verification", "Steps" to "Order of work"). Extra sections are fine
anywhere; the ten above must be present and in that order. A `compare` block can stand in
for Now and Target. Steps and Proof are required for a repo card only.

An outcome (`kind: outcome`, or any file named `context.md`) has the record's five
sections: Where it stands, What is next, Why this shape, Open questions, Evidence (plus the
PR body where there is one). One that ships a change also redraws its boards at the built
head and gives a reading order ("The outcome's boards", below).

**An outcome explains what was actually done** (c-719). The five sections are a short frame,
a few lines each, not the whole record. Between them go sections of the house's own (extra
sections are fine anywhere) that explain the work to someone who was not there: what was
found, how it works now, what was tried and dropped, and why. Prose comes first, with
tables where there are numbers or cases to set side by side. A board or a diagram is used
only where it explains better than prose, and each one in the outcome carries a sentence
or two saying what it shows; nothing here asks for a board beyond the ones a card already
draws (a code card's flow and Code flow boards, a research card's one findings board). The
record a card starts with says this in a comment (`<!-- ... -->` that opens a line), which
the page never draws. A PR context (`kind: pr`)
has its seven: Summary, Plan,
Design decisions and constraints, Review findings, Files touched, PR body, Open threads.

## A research card's outcome (`kind: research`)

A research card's outcome IS the research (c-719): the findings themselves, explained, in its
one outcome file (`context.md`), read on the outcome page. There is no separate report file
and no link to one. Its light contract (C26) is four sections: **Findings** (what was found,
each with where it came from), **What it means**, **What is next**, and **Evidence** (what was
looked at, as links, `path:line`s, pictures or code). Sections of the house's own may sit
between them, as in any outcome; there is no Risk and no PR body. A research card's record
opens in this kind (`planbrief.context_skeleton`, for a card whose `options.kind` is
`research`). A work research card may embed its one findings board under Findings, with a
sentence or two saying what it shows.

The kind follows the role: a card's `context.md` that names any kind but `outcome` is read
as `kind: outcome`, held to the outcome's sections (and its Risk and boards when it ships),
and the lint names the mismatch; `research` and `report` are kept on a research card or a
card with no repo (it ships no code), and `review` on a review card. A card's plan that names
any kind but `plan` is read as a plan, and the lint names that too.

`kind: report` is held to the same four sections: a report is findings by nature, and before
c-719 it was linted as a plan, which asked it for a Goal, Decisions and Steps.

## A review card's outcome (`kind: review`)

A review card (lane RC) reviews a colleague's pull request, and the user's Approve POSTS what the
outcome says: each finding the user kept as an inline comment at its `path:line`, one summary
comment (the summary paragraph and the counts), and the verdict. So the outcome is
`context.md` with `kind: review` in its frontmatter, and its shape is held by C28 to C32.
Each finding is ONE `finding` block (lane FC): everything about it in one place, which the
deck draws as one card with the code around its line pulled from the worktree when the page
opens. Never copy code into the outcome: there is no Snippets section.

````text
---
kind: review
card: c-123
title: "Review: Tidy the loader's page cap"
repo: cloud
pr: 4150
---
# Review: Tidy the loader's page cap

What the change does, in one paragraph: the summary comment starts with it.

## Orientation

What it does and how, a paragraph; then its code path as a board pushed with
`keel board push --new --card c-123` and embedded by id; then the reading order.

```board The loader's code path
b-012
```

1. `app/loader.py:12` where a page is asked for
2. `app/loader.py:40` the new constant

## Findings

```finding r1-f1
severity: high
at: app/loader.py:40
claim: The cap is read before the settings load, so it is always the default
evidence: `CAP` is assigned at import, and the settings load later, in `main()`
verifier: kept
suggestion: Read the cap inside the call that pages
comment:
  The cap is read at import time, before the settings load. Could it be read in the call?
choice: post
because: high, and the verifier kept it
```

```finding r1-f2
severity: low
at: app/loader.py:12
claim: A local name shadows a builtin
verifier: disputed
  for: `list` is rebound in the loop
  against: the builtin is never used in this function
comment: Small one: `list` shadows the builtin here.
choice: drop
because: low, style only
```

## Verdict

```decision verdict
q: What does your review say overall?
option comment: Comment only
  gets: ...
  cost: ...
option changes: Request changes
  gets: ...
  cost: ...
option approve: Approve the pull request
  gets: ...
  cost: ...
rec: changes
because: the high finding is kept
other: no
```
````

A finding's id is the core's with the dot as a dash (`r1.F1` is `r1-f1`). Its fields:

| Field | What it holds |
|---|---|
| `severity:` | critical, high, medium or low: the core's |
| `member:` | a feature card only: the pull request it is posted on (`cloud#4150`) |
| `at:` | `path:line` or `path:start-end`, where the comment is posted; it resolves at HEAD of the worktree (the member's, on a feature card) |
| `claim:` | the one line it says, drawn in the card's head |
| `evidence:` | why it holds |
| `verifier:` | kept, unverified or disputed; a disputed one carries both sides on indented `for:` and `against:` lines |
| `suggestion:` | what to do about it |
| `comment:` | the words to post, polite, specific and in the user's voice, on the indented lines under it: a blank line starts a paragraph, a list item keeps its line, and any other line break is a space, as markdown reads it |
| `choice:` | post, edit or drop: your recommendation (post for high and critical, drop for low unless it is clearly worth the author's time) |
| `because:` | why that choice |

The user sets each finding to post, edit (the comment field is the user's to rewrite, and the user's words are
what posts) or drop, and picks the verdict: comment only posts no verdict, request changes
and approve post that answer. A finding the user does not touch takes your choice.

**A feature card** (lane GRP: one story's pull requests reviewed together, the card's
`options.review_members`) writes the same kind with three differences, held by C32. The
frontmatter has `members: cloud#4150, webapp-react#2200` (the card's own list is what the
lint trusts; this line is for a reader). Every finding has a `member:` line, and its `at:`
must resolve in that member's worktree. And the Verdict section has ONE decision per member,
`decision verdict-cloud-4150` and `decision verdict-webapp-react-2200` (the label in lower
case, every other character a dash), each with the same three options and `other: no`, and
no other decision. The orientation is one for the whole feature, its board drawing the path
across both repos. The user's Approve posts each kept finding on its member's pull request, the
summary on every member, and each member's verdict on it.

**The old shape** (one ```batch findings of rows, a ```copy comment <row> block per row, and a
Snippets section) is still read, posted and drawn for an outcome that was written in it
before lane FC, but `kb stage review` refuses a new outcome in it.

## Plain markdown

Paragraphs, `##`/`###` headings, bullet and numbered lists (two levels), `**bold**`,
`*emphasis*`, `` `code` ``, links. A list item that opens with `**Lead:**` keeps its lead.

- **Task list**: `- [ ] todo` / `- [x] done` becomes a checklist.
- **Table**: GFM pipes. The paragraph directly above a table is its caption and is required
  (what the rows prove). A cell that opens with `[ok]`, `[warn]` or `[bad]` gets a tone chip.
- **Callout**: `> [!info] Title`, then `>` lines. Tones: `info`, `warn`, `error`,
  `success`, `settled` (a point decided in discussion).
- **Pictures**: `![caption](assets/shot.png){phone}` on its own line; the hint is `phone`,
  `desktop` (the default) or `wide`. Several lines in a row become a gallery. Paths resolve
  against the plan's own directory and are served by token.
- **References** are linked by themselves: `c-123` (a card) and `path/to/file.py:40` or
  `path/to/file.py:40-52`, in backticks or not. Every path ref is checked against the
  worktree at HEAD. A ticket and a change are linked in the card's own space's shape, from
  its pack's `[terms]` (c-630): in the work space `sc-12345` (a story) and `PR #12`. A
  personal card links neither.

## Fenced blocks

The fence's language names the block; its info string (the rest of the fence line) is its
id or title; its body is small `key: value` lines. An indented line belongs to the line
above it.

### decision (the one that matters most)

````text
```decision store
q: Where do the user's answers live?
why: One store is a hard rule.
option card: As events on the card
  gets: one store, the stream tells the page
  cost: a new event kind
option file: In a file beside the plan
  gets: nothing new in the schema
  cost: a second store that must agree with the board
rec: card
because: the board is the only state
other: yes
after: another-decision-id
```
````

Two to four options, each with an id, a label, a `gets:` and a `cost:` (the cost as visible
as the benefit). Exactly one `rec:` naming an option, with its `because:`. `other: no` hides
"Something else". `after:` says this one depends on that decision, and the page shows it. The id is what
the user's answer is stored against: keep it when you revise.

### batch (many small verdicts: triage, replies to a review)

````text
```batch findings
q: What to do with each finding
choices: fix, defer, drop
f1: The cap is off by one | fix | a real bug
f2: A comment is stale | drop
```
````

One row per item: `id: text | recommended choice | why`. The user sees every row with its
recommendation pre-selected and changes only what the user disagrees with. A row id may hold a
dot (`webapp-react.c21`, a reply to the second pull request of a two-repo card), kept as
written and up to 96 characters; that is the batch's alone, and every other block's keys
stay letters, digits, `_` and `-`.

### A real flow is a board

The flow of a repo card (what happens, end to end, and where it runs in the code) is a
BOARD you push, and the plan embeds it by id. It is then on the board page too, listed
under the card, with its notes, steps and tables, and one fix shows in both places.

```text
keel board list --card c-123                      # what this card already has: extend or reuse it
keel board push --card c-123 --new --file flows.txt
                                                  # a fresh board per `board "<title>"` line in the
                                                  # file; prints each id, say b-012 and b-013
```

Draw it as rich as your context allows. If you already know the flow, draw the whole walk
now: steps and notes on the nodes, a table where the numbers are. If the flow is not known
yet, a lean board (titles, detail lines, icons, groups) is a fine start, and the full walk
comes with the outcome.

````text
```board Event flow, start to finish
b-012
```
````

Revise it by pushing to the same board without `--new` (the same title continues it), never
by pasting its lines into the plan. A board the card already has (`keel board list`) is
embedded by its id as it is; it does not need drawing again. Inline board lines and `mermaid` stay for SMALL pictures beside it
(a state machine, a three-box sketch); they are not the flow.

### The outcome's boards: redrawn at the built head, and a Code flow board

A plan's board is drawn before the code exists. An outcome that ships a change (C33) draws
the flow again at the head that was BUILT, in a background subagent at Verify so it costs
nothing on the path to review:

1. every board the plan embeds, redrawn as the same board (`keel board push --board <id>`,
   which replaces what it shows and keeps the plan's lines in its log, c-604);
   one left as it was is tagged "from the plan, not updated" on the outcome page;
2. ONE new board titled `Code flow: <what it does>`, drawn so the user can read the code by it: a
   node per unit (function, class, module) with its path as the detail, grouped per module
   or service; edges in call order, each labelled with the call; a `note board` saying to
   follow the numbered steps; one `step` per node, in order, carrying ONE worked example
   with its real values; a `code` block where the lines matter; a `note` naming the tests
   that pin the unit (c-272's b-009 is the model);
3. each board embedded by id, and under `## Why this shape` a `### Read it in this order`
   list, numbered, one `path:line` per step.

The subagent writes the board blocks and the reading order to `outcome-boards.md` in the
card's directory, never into `context.md`; the house joins it before `kb stage review`,
merges its text under Why this shape, and checks the lines against the final head after the
review's fixes. A card with nothing to land says `change: none` in the outcome's frontmatter
and draws none of this; a docs-only change says `change: docs` and gives the reading order
(the pages to read, in order) without a Code flow board:

````text
## Why this shape

One paragraph on why it is built this way.

```board Code flow: a replay run, start to finish
b-160
```

### Read it in this order

1. `app/replay.py:40` the route takes the run and checks the account
2. `app/replay_jobs.py:12` the task that runs off the request thread
````

### Open questions

Under `## Open questions`, a plain list. Put your recommendation in the item after
`Recommend:`; the user can accept it or answer in words. `None.` when there are none.

```text
- Should Approve fill every unanswered decision? Recommend: yes, and say so on the card.
```

(A fenced `questions` block with `q:` / `rec:` / `why:` lines is the same thing.)

### The rest

| Block | Body | For |
|---|---|---|
| `compare <title>` | `left: Today`, `right: After`, then rows `aspect \| left \| right`; a row whose aspect is `image` takes two picture paths | current against target, the same system on both sides, row by row |
| `options <id>` | `option a: label` with indented `summary:`, `pro:`, `con:`; `rec: a`; `decision: <id>` to link the one that answers it | a comparison of approaches |
| `steps <title>` | one step per line: `[todo\|doing\|done\|blocked] Title \| detail` | build order, phases |
| `board <title>` | `b-012` (a board you pushed, embedded by id), or board ops in the board's line language | THE flow: see "A real flow is a board" below |
| `mermaid <title>` | a `flowchart`, a `sequenceDiagram` or a `stateDiagram-v2`, nothing else | a small picture beside the flow (at most 12 nodes), drawn by the board's own renderer |
| `<lang> <path[:lines]> \| why` | the code | a snippet: the path and the reason sit above it |
| `diff <path> \| why` | a unified diff | a change |
| `stats` | `label \| value \| sub \| tone` per line, one to six | numbers at a glance |
| `details <summary>` | markdown | long evidence, logs |
| `copy <title>` | text, kept exactly | a PR body, a commit message, a message to paste |
| `finding <id>` | severity, member, at, claim, evidence, verifier, suggestion, comment, choice, because | one review finding, whole: see "A review card's outcome" |

## What the lint refuses

`kb lint <card> [--file plan.md]` prints every finding; `kb stage <card> planning --plan
plan.md` refuses a plan in this format with any error, and `kb stage <card> review` does
the same for a `context.md` in this format. The rules are the contract's numbers:

| Rule | Refused when |
|---|---|
| C1 | no summary paragraph first, or it runs past 90 words |
| C2 | Goal, Now or Target is missing, or the sections are out of order |
| C3 | a compare row is missing a side, or a compare names no sides |
| C4 | a repo card's plan embeds no board BY ID (a `mermaid` or inline board alone is a finding that prints the push command), or any embedded id does not resolve |
| C7 | a `path:line` does not exist at HEAD of the card's worktree (a plan's: at its `at:` commit); a dependency's code (`node_modules/`, `site-packages/`) is never checked |
| C8 | a code block has no `\| why`, or (not a shell) no path |
| C9 | Proposal is missing or empty |
| C11 | no decision, no `> [!settled]` callout and no `None: <why>` under Decisions; a decision with fewer than two options, or an option with no cost |
| C12 | a decision with no `rec:`, a `rec:` that is not an option, no `because:`; an open question with no recommendation |
| C14 | `after:` names a decision that is not on the plan |
| C16 | a decision the user answered on the last round is still on the revised plan |
| C17 | Risks is empty, or says `None` without a reason |
| C18 | a repo card's Steps or Proof is missing or empty |
| C19 | Out of scope is missing or empty |
| C20 | a table with no caption line above it |
| C21 | a paragraph over 180 words (a warning) |
| C24 | an em-dash anywhere |
| C26 | an outcome missing one of its sections (a research or report outcome: Findings, What it means, What is next, Evidence), or Evidence that names no artifact |
| C27 | the outcome of a card started with the pre-gate pipeline has no `## Risk`, or its Risk names no level (low, medium or high) |
| C28 | a review (`kind: review`) does not open with `## Orientation`, or its orientation says nothing, embeds no board by id, or gives no reading order of `path:line`s |
| C29 | a review's `## Findings` is not one `finding` block per finding (or `None:` and why), a finding has no valid severity, no `at: path:line`, no claim, no `comment:`, a verifier word or a `choice:` outside its set, a disputed finding lacks a side, a finding that survived the verifier is not a block, or the outcome keeps a Snippets section or the old batch shape |
| C30 | a review has no `decision verdict`, has another decision, offers anything but comment, changes and approve, or leaves out `other: no` |
| C31 | a re-review raises a finding at a `path:line` the user posted or dropped last round, on lines that did not change since |
| C32 | a FEATURE review (one story's pull requests together, lane GRP) has a finding with no `member:` or one that is not a member, a finding whose `at:` does not resolve in its member's worktree, a member with no or two `decision verdict-<repo>-<number>`, or any other decision |
| C33 | an outcome of a card started with the pre-gate pipeline embeds no board pushed after the user's plan approval (only the plan's boards, unchanged, or none), or has no NUMBERED list of `path:line`s under `## Why this shape`; each embedded board last pushed at or before the approval is a warning ("from the plan, not updated"), and the whole rule is a warning for an outcome already at review, shipping or done. Frontmatter `change: none` (nothing to land) is exempt, and `change: docs` (a docs-only change) needs the reading order but no board |

What is not checked, because no mechanism can judge it: whether a claim is true (C7 checks
only that the line exists), whether the right diagram was drawn, whether a question is one
the code could have answered (C13), whether an assumption that would change the
recommendation is said (C15), and whether a frontend change shows the UI (C6: no card field
says which repos are frontend).

## What the user does with it

On the phone the plan opens on **Decide**: every decision with its recommendation already
selected, the batch rows, the open questions, the user's notes, and Send. **Read all** is the whole
document. On the desk the document and the round sit side by side. A tap on an option, a row
or a reply is stored at once on the card; selecting any words, or tapping any block, pins a
note to it. **Approve with these answers** and **Send back with notes** send the whole round
in one prompt, which lists every decision (the user's picks marked apart from the recommendations
the user left standing) and every note with the words the user selected kept apart from what the user wrote.
**Ask** puts one question to the house at once, without sending the plan back: the house is
resumed with it and answers with `kb reply <card> --ask <id> --text "..."`, which pins the
answer under the user's question. Do not revise the plan or move the card on an Ask; the user's round
waits for the user's Send.
