# The board

The board is where a house or the talker SHOWS the user something instead of telling the user. It
draws with a tiny line language, Keel renders it, and what was drawn is saved as a record the user
can find again months later. It is one deck route, `/board`, and one verb, `keel board`.

**A board is ONE model, seen three ways.** One diagram (groups, nodes, edges, marks) with
attachments hanging off its nodes and off the board itself, shown as a *diagram*, as an
*outline* or as a *walk*. It is not a filmstrip of pictures: many frames on one topic are
hard to take in, so a board is one view that can be looked at in different ways (as a diagram,
as a list), never several frames.

> if I ask for a second thing that doesn't fit with the first but still belongs to the
> house, it can be another board, not a frame

So `frame` is gone from the grammar, and the second picture is `board new`, which starts a
second BOARD for the same source.

The other half of the point is in one sentence: **an agent never sends HTML, SVG, a script
or a coordinate.** It sends lines. Our code decides what they mean and where they go.

- *Safety.* A house may have read a hostile web page. Its output must never run in the
  deck's origin, where the approve verbs live. A line language has nowhere to hide a
  script, and `app/ui.board.js` builds every node with `createElement` and `textContent`.
- *Speed.* Output tokens are the latency. Twenty lines arrive in a couple of seconds; a
  hand-written diagram does not.
- *One bad line costs one line.* A line that does not parse is SKIPPED with its reason
  recorded, and everything around it is drawn without it.

There is **no erase**. Re-declaring a node id updates it, `mark` highlights, attachments
append, and a picture that does not belong on this one is a new board. That is what makes a
board a record rather than a document: the ops are append-only, so what the user was shown at the
time can always be replayed.
The one way to draw a board over is a REDRAW (`keel board push --board b-NNN`, c-604): the
model starts afresh at its marker, and the lines before it stay in the log.
A redraw never changes what the user's APPROVED plan shows (c-604 review): the plan page's embed is
the board as it stood at the user's approval (`boards.lines_at`, from the log's own stamped markers,
so nothing new is stored), and its Open board, walk and drawing links carry `?upto=<n>`, which
the board page draws as that many lines, marked `as approved in the plan`, off the live
channel. The outcome's embed is the board now, and one redrawn since offers `As approved in
the plan` beside it for the before and after.

## The line language

One op per line. A quoted string may hold spaces. A `#` line is a comment and a ``` line is
a stray fence mark; both are skipped silently. Anything else that does not parse is skipped
with its reason, never fatal.

```
board "The memory tier system"                   # the TOPIC: a new topic is a new board
group pushed "Injected every session"
node index file "MEMORY.md index" in pushed "the triggers"   # `in <group>` and a "sub" are optional
edge index -> bodies "a pointer the model must follow"       # also <-> and --
mark index accent                                # accent, good, warn, crit
note index "The index line is the TRIGGER, and it is all that is injected."
step board "A session starts, and the pushed surfaces are in its prompt"
table board "Where a rule belongs"
cols Surface | Reaches
row ~/.claude/CLAUDE.md | every session
code index "an index line is a trigger"
lang markdown
line "- [worktree-workflow](worktree-workflow.md): the wt stack."
path bodies "state/cards/c-420/probe.py" size "2 KB" from house
board new "The second picture"                   # a second board outright
board rename "What it should have been called"   # rename THIS board, start nothing
```

| Op | What it does |
|---|---|
| `board "<title>"` | the board's TOPIC. A title that is not this board's topic starts ANOTHER board; the same topic continues this one |
| `board new "<title>"` | starts a SECOND board outright, even under the same title |
| `board rename "<title>"` | renames THIS board and starts nothing |
| `group <id> "<label>"` | a dashed container; declare it before the nodes that name it. Its id may not be a node's, nor a node's id a group's: the push skips the line with the reason (c-602), because the drawing once walked a node `lint` in a group `lint` as its own parent and hung; `ui.board.js` now keys nodes and groups apart, so a board stored that way still draws |
| `node <id> <icon> "<label>" [in <group>] ["<sub>"]` | one box, sized to its own label |
| `edge <a> <arrow> <b> ["<label>"]` | `->` one way, `<->` both, `--` neither |
| `mark <id> accent\|good\|warn\|crit` | highlights a node already declared |
| `note <node\|board> "<markdown subset>"` | `**bold**`, `` `code` `` and line breaks, nothing else |
| `step <node\|board> "<text>"` | one step; steps are numbered by PUSH ORDER across the whole board |
| `table <node\|board> "<title>"` | opens a table; its `cols` and `row` lines follow |
| `cols A \| B \| C` | the header row, before any `row` |
| `row a \| b \| c` | one row of the table above it |
| `code <node\|board> "<title>"` | opens a snippet; its `lang` and `line` lines follow |
| `lang <name>` | the language shown above the snippet above it |
| `line "<text>"` | one line of it, kept exactly |
| `path <node\|board> "<path>" size "<size>" from <who>` | one file, carried with the push and served (below) |

### The grammar card, and its version

**The grammar is said in ONE place and embedded everywhere else** (C4, 2026-09-23). A house
started before a grammar change draws the old grammar (c-302): it
writes `step "<text>"` and `frame` lines after both have gone, and most of its
lines are refused (21 of 27 on the board where this was measured). A grammar that reaches a house through copies kept by hand (the house
contract, the talker's memory, this page) cannot say which version it is.

So `keel/boardgrammar.py` holds `GRAMMAR_VERSION` and `grammar_card()`, built from the
parser's own tables (`OPS`, `ICONS`, `MARKS`, `ARROWS`, the caps, `RETIRED`), and each copy
(`boardgrammar.copies`: this page, and the talker's `drawing-on-the-board.md` wherever its
memory is read from, the install's `memory/talker` once it holds it, c-722) embeds the card
in a fenced block whose language is `grammar`. A house's brief does not copy it: its board section is generated at
brief time (`boardgrammar.brief_block`, through `prompts.abilities`, for every house with a
shell), so a new brief always carries the current card. That section also says, in short,
what this page explains: one diagram per board, the title is the topic, push only to your
own card, a `path` line hands the user a file, the user's files land in `inbox/`, a fenced `board` block
in a spoken answer, and a `board report:` line means draw it again. Every `board push` the
brief shows, and every one the outcome boards backfill sends (`outcomeboards.prompt_for`),
names the card and its directory literally (`prompts.literal_board_push`, r-56,
c-723): the house guard reads a `push` word beside a word the shell fills in as git run
through a variable ([flows](64-flows.md), "The push fence"), so `--card $KEEL_CARD` as the
brief once wrote it was refused, and the guard is not loosened for it. It left the house
contract in c-603, which had grown to four times its 60-line cap around it. `tests/test_boardgrammar.py` fails on a copy
that has drifted, and `python3 -m keel.boardgrammar --write` rewrites them all. The card
rides on a voice conversation's first sentence (`prompts.converse`), and on a later sentence
(`prompts.converse_more`) when the card has no `board grammar v<N>` note saying this house
was given this version.

```grammar
Board grammar v2: one op per line. A line that does not parse is skipped with its reason and the rest still lands.

board "<title>"          the TOPIC: a new title starts a new board
group <id> "<label>"         an id no node has
node <id> <icon> "<label>" [in <group>] ["<sub>"]
edge <a> -> <b> ["<label>"]     also <-> and --
mark <node> accent|good|warn|crit
note <node|board> "<text>"
step <node|board> "<text>"
table <node|board> "<title>"
cols A | B | C            after a table
row a | b | c             after its cols
code <node|board> "<title>"
lang <name>               after a code
line "<text>"             after a code, kept exactly
path <node|board> "<path>" size "<size>" from <who>
board new "<title>"      another board, even under the same title
board rename "<title>"   rename this board, start nothing

Attachments (note, step, table, code, file) hang on a node or on the board; one on a node nobody declared is skipped.
Icons (24; anything else becomes box): laptop, server, cloud, database, phone, mic, speaker, globe, network, lock, key, file, folder, git-branch, bot, user, clock, list, cpu, hard-drive, shield, box, terminal, zap.
Caps: 12 nodes per board (a push past it draws nothing), 120 attachments per board, 240 characters per quoted string, 400 lines per push.
Gone: frame (frames are gone: attach to a node or start a new board with `board new "<title>"`); text (text is gone: a note is `note <node|board> "<text>"`).

Write each step as one or two plain sentences meant to be read in order, like a walk: what happens here and why it matters, not the node's label said again.
In a spoken answer the lines go in a fenced block whose language is `board`. Put one or two sentences before the block; nothing after it is spoken, and what he hears in its place is what the push reported.
```

**A step is written to be read, in order** (Z2, lane Z, c-453). The walk is visual and on
demand: the user steps through it when it suits them, and each step shows as a callout from its lit
node. So the card's `STEP_RULE` asks for one or two plain sentences per step, what happens
there and why it matters, never the node's label again; the plan format card carries the same
sentence for the flow a plan embeds. Wording is not grammar, so `GRAMMAR_VERSION` stays at 2
(Z-2), and the card has no audio or clip field: the recorded half of c-453 was dropped.

**The previous grammar is translated, not refused.** `boardgrammar.translate` is asked about
a line only after the current grammar refused it, in the store's planning pass
(`boards.read_previous`), so every way in gets it: a bare `step`, `note` or `text` hangs on the
board, a bare `path` too, `frame table` and `frame code` open that attachment on the board,
and any other `frame` line is dropped with a skipped row ending "dropped: written for the
previous grammar". `ops.log` holds the TRANSLATED line, so the deck reads it in the grammar it
knows, and the push's answer counts them as `translated`.

**Five kinds of attachment**: `note`, `step`, `table`, `code` and `file` (a `path` op). Each
one hangs on a NODE or on the BOARD. `board` in that position always means the board, even
if a node happens to be called `board`: a rule the user can predict beats one the user has to look up.
An attachment on a node nobody has declared is skipped, so a typo leaves nothing orphaned.

**`cols`/`row` continue the last `table`, and `lang`/`line` continue the last `code`.** A
`row` with no table open, or before its own `cols`, is skipped with its reason.

**The icons are a closed set of 24**: `laptop`, `server`, `cloud`, `database`, `phone`,
`mic`, `speaker`, `globe`, `network`, `lock`, `key`, `file`, `folder`, `git-branch`,
`bot`, `user`, `clock`, `list`, `cpu`, `hard-drive`, `shield`, `box`, `terminal`, `zap`.
A name outside it falls back to `box` rather than refusing the node: a wrong picture is a
smaller failure than a missing one.

### The title is the topic

**A `board` line whose title is not this board's title starts another board.** A push with
no `board` line continues the live board, the same title continues it, and renaming it is
its own word.

It was a rename, and that cost a real board. Asked to explain how input becomes
a diagram, Harbor wrote a fence opening `board "How drawing on the board works"`; its live
board was `b-001`, "The memory tier system", with nine nodes on it. So the memory board was
RENAMED to the drawing board, the drawing board's own nodes hit the twelve node cap three
in, and then every attachment hanging on a node that had been dropped was refused in turn:
25 skipped lines, all of them `no node called 'meaning' on this board`. Two boards' worth of
thinking in one, under the wrong name, most of it gone.

Nothing about that push was ill-formed. It said what it was about, in the one op that exists
for saying so. So the title means what it reads as.

**This is the SOURCE'S rule, not Harbor's.** A card has as many boards as it has pictures,
and a house splits on a new topic exactly as Harbor does: "a user flow diagram and then a
database schema diagram both belong to the same story but are different, and the node cap
would hamper cramming them into one". One topic per board. The card's pane lists all of
them, newest first with the live one marked, the Saved list groups them under that card, and
`keel board list --card c-NNN` prints them.

Titles are compared as TOPICS: case, punctuation and spacing folded away (`boards.topic_key`),
because a model writes the title again from its own memory of the conversation and "the
memory-tier system." is the same topic as "The memory tier system". A board that has nothing
on it yet is always NAMED rather than left behind, so the first push of all, and the board
`board new` has just minted, take their title from the line that opens them.

**The caps**, all held by the server, because a cap the server does not hold is a cap an
agent can talk its way past: 12 nodes per BOARD (the thirteenth is refused, with the reason
saying to start another board), 120 attachments per board, 240 characters per quoted string,
48 per id, 6 columns per table, 400 lines per push.

**`frame` and `text` are retired**, and they are answered BY NAME rather than as unknown
ops, because a house or a talker carrying the old grammar should be told what to write
instead on the line it got wrong: "frames are gone: attach to a node or start a new board
with `board new "<title>"`", and "text is gone: a note is `note <node|board> "<text>"`".

### What is refused, and what that costs

Refusing happens in two places and means the same thing both times: the line is written to
`skipped.log` with its reason, and nothing else changes.

- **Grammar** (`boards.parse_line`): an unquoted label, an unknown op, an unclosed quote, a
  string past its cap, a retired op.
- **Meaning** (`boards.apply_op`), which can only be judged against the board it lands on:
  an `edge` to a node nobody declared, a `note` on a node nobody declared, a `row` before
  its `cols`, a `line` with no `code` open.

**The node cap is the one refusal a push does not survive.** A thirteenth node used to be
skipped like any other bad line, and what followed was a diagram with holes in it and then
every attachment hanging on a node that had been dropped, refused one at a time. A push that
would take a board past twelve is refused WHOLE (`TooManyNodes` becomes a `BoardError` in
`plan_push`), nothing is drawn, nothing reaches the skipped log, and the one line of reason
names both ways out: `board new "<title>"`, or a title of its own. That is why a push is
planned before it is written: `plan_push` decides what would happen and `write_plan` does
it, so a refusal can cost nothing.

### One grammar, two parsers

`keel/boards.py` decides what may be written; `app/ui.board.js` parses the same lines to
draw them. They are held together by `tests/test_boards.py`, which runs BOTH over
`tests/fixtures/board-lines.txt` (one row per line: `OK` or `BAD`, a tab, the line), folds
one whole board through both models and compares (`tests/fixtures/board-model.js`), and
compares the deck's five vocabulary arrays name by name with Python's. A new op goes in the
fixture first. The node runs are skipped where node is not installed; the vocabulary
comparison is a source read and always runs.

The deck's half is deliberately the more permissive of the two: it enforces the grammar and
ignores what does not fit, because every line it reads has already been through the
server's half. A record written by a newer server still draws on an older deck.

## The store

`state/boards/<b-id>/`, one directory per board, ids `b-<n>` minted the way a card's is.

| File | What is in it |
|---|---|
| `files/` | a talker board's own file copies. A card's live in `state/cards/<id>/board-files/` instead, beside everything else that card stores |
| `inbox/` | what THE USER dropped on a talker's board. A card's drop lands in `state/cards/<id>/inbox/`, where the house is already pointed |
| `.attached/<source>/` | where a file waits between `keel board push` staging it and the push that names it. Pruned after an hour, and out of the backup: a restored one is a file nothing is ever going to push |
| `.trash/<b-id>/` | a board the user (or its own house, or Harbor) DELETED, moved here whole with a `deleted` block on its record (who, when, as what actor), restorable for 30 days and then purged by the drain, leaving `<b-id>.purged` so the id is never minted again ("Deleting a board", below) |
| `.lock` | the store's one write lock. Every write here reads, changes and rewrites a whole file, and `next_id` scans the directory `create` then adds to, so two at once mint the same id or leave a record counting nodes `ops.log` does not hold. `flock` is per open file description, which serialises threads of one process and processes on one host alike. The verbs take it; the helpers under them never do, or a push would deadlock against the lock it is already holding |
| `board.json` | `id`, `title`, `summary`, `source` (`{kind: "card"\|"talker", card}`), `actor`, `created`, `updated`, `closed`, `nodes` and `attachments` (counts), `labels` and `said` (what `find` scores), `files` (the path each `path` op named, against the copy kept for it), and `last_push` (the duplicate rule, below) |
| `ops.log` | every accepted line, append-only, with a `# push <n> <ts> <actor>` marker line at the start of each push, or `# redraw <n> <ts> <actor>` at the start of a redraw (`--board`), where every reader starts the model afresh |
| `skipped.log` | one row per refused line: the stamp, the reason, the line |

The whole tree is under `state/`, so it is inside the `keel` backup set as it stands
([the backup](85-backup.md)); nothing in that set's exclusion list touches it.

**The LIVE board of a source is its newest board that is not closed**, ordered by
`updated`. A push with no live board creates one, which is why `keel board open` bumps
`updated`: reopening an older board is what makes it live again. `updated` is stamped to
the microsecond for exactly that reason, since two boards touched in the same second would
otherwise tie and the tie-break would decide which one a push continued. Because `updated`
moves on open and close too, WHEN A BOARD WAS LAST DRAWN ON is its own field: a listing row
and `board.show` carry `pushed` (`boards.pushed_at`: `last_push`'s time, else `created`),
which is what an outcome's C33 compares with the user's plan approval (c-602, [plans on the
deck](47-plans.md)).

A board's title is, in order: `--title`, the `board` op, the name it already has, the first
group's or node's label, the card's own title.

### The same push, said twice, lands once

One `board` block in a spoken answer is READ TWICE: by the stream as the fence closes, and
by the pass over the finished text. On **b-003** that drew the same ops onto the board
twice, 6 ms apart, with `'```' is not an op` in the skipped log to show why: the streamed
reading carried a trailing fence mark the finished one did not, and the pen compared the raw
bodies. Three things stop it now, and each has its own test because each alone would be
enough:

1. **No fence mark survives into a body.** `sentences.strip_fences` takes it out of both
   readings, and `boards.parse_line` treats a ``` line as a blank rather than as an op.
2. **The pen compares NORMALISED op sequences** (`sentences.normalise`: blanks, comments and
   fence marks dropped, whitespace collapsed), so two readings of one block are one push.
3. **The store refuses an identical normalised push from the same caller within 10 s.** A
   `dup` row goes in `skipped.log` and the push answers `ok` with `duplicate: true`, because
   from the caller's side the ops ARE on the board and saying no would have a house tell the user
   it could not draw something the user is already looking at.

## The verbs

`keel board <verb>`, with `--json` on every one of them.

| Verb | What it does |
|---|---|
| `keel board push [--card c-NNN \| --talker] [--title "..."] [--file <path>] [--new \| --board b-NNN]` | appends ops (stdin, or `--file`) to the source's live board, creating one when there is none. Prints the board id, the node and attachment counts and the deck URL. A `board new`, or a `board` line with a different topic, starts a second board inside the push and the result names the last one. `--new` (P4-3) starts a FRESH board even when one is live, and inside that push EVERY `board` line starts another (a `board rename` still renames): a plan's three flows are one file and one call. The board that was live stays open, as after `board new` (B3, B6); the newest is the live one. `--board b-NNN` (c-604) REDRAWS that board: the push replaces what it shows under the same id, the lines before its `# redraw` marker stay in the log as the record, only the source's own open board may be redrawn, a `board new` line inside it is skipped, and a redraw that accepted nothing writes nothing. It is how an outcome redraws a plan board at the built head as ONE picture; appending there drew the plan's edges and steps and the build's side by side |
| `keel board list [--card c-NNN] [--limit N]` | every board, newest first, with its source, its counts and whether it is live |
| `keel board find "<words>"` | boards matching those words, best first |
| `keel board show <b-id>` | that board's ops |
| `keel board open <b-id>` | makes it its source's live board again, so the next push continues it |
| `keel board new --from <b-id> [--title "..."]` | a new live board holding a copy of its ops |
| `keel board close <b-id> [--summary "..."]` | closes it and writes its summary (its node labels joined, unless one is given) |
| `keel board delete <b-id> [<b-id>...]` | moves those boards to the trash, restorable for 30 days: a house its own card's boards, Harbor its own talker boards, the user any. Refused whole when one of them is not the caller's |
| `keel board restore <b-id>` | brings a board back from the trash, the user's alone (the deck, or `KEEL_TOKEN` at the desk) |
| `keel board list --deleted` | the trash: who deleted each board, when, and when it is purged |

`find` scores whole words over four places, weighted: the title (4), the summary (2), what
the attachments say (2) and each node label (1). Both sides are cut on non-word characters,
so `MEMORY.md` in a search finds `MEMORY.md` in a label, and a one-letter word is dropped
because "a" is in almost every label. There is no stemming and no ranking model: the corpus
is the user's own boards, tens of them, and a rule the user can predict beats a score the user cannot.

### Who may push

**Reading is open; writing is not.** `list`, `find` and `show` are open to anyone, exactly
as `kb show` is open on any card. The four verbs that CHANGE a board (`push`, `open`,
`new`, `close`) are refused unless the caller owns that board's SOURCE, because `open`
decides which board the next push lands on and `close` ends a sitting that was not the
caller's. `delete` and `restore` hold a stricter rule of their own, where a bare terminal is
not the user without the user's token ("Deleting a board", below). `keel/boards.py` holds that rule (`may_change`). The deck's own tap is the user, and `keel/actions.py`
refuses a body that names a `caller`.

`new --from` is the one with a twist: a caller may COPY any board it can see, and the copy
always belongs to the CALLER. A house forking the talker's board gets a board on its own
card, never a talker board, because a board on somebody else's source would become that
source's live board and their next push would land on it. Only the user, who owns every source,
gets a copy on the original's.

**What that rule rests on, said plainly.** A house's `card` is the `KEEL_CARD` its harness
gave it, and the store scopes the house to that card without proving the claim: the
boundary is the Unix user and the token, as with every other `kb` verb (`--actor human` is
the one claim that needs a secret, and it needs `KEEL_TOKEN`). Proving that claim per card
is a change to `kb`'s trust model and not the board's, so it is on the list of what is still
owed in `<install>/history/docs/blackboard.md`.

The actor is decided by the environment, never by the command line, exactly as `kb`'s is.

- **A house.** `KEEL_CARD` says which house this is, so `--card` must equal it and
  `--talker` is refused. The board records `actor: "house"`.
- **The talker.** `--talker`, with `KEEL_TALKER` in its environment. Its boards are linked
  to no card.
- **The user**, from a terminal or from the deck: `actor: "human"`.

**A confined house draws too.** The board fence (`bin/keel-board-fence`) allows one plain
command with no pipe, no redirect and no heredoc, which is the whole point of it, so
`keel board push` also takes `--file`: the house writes its lines into its own card
directory with Write and names that file. `keel/prompts.py` puts that command in the
confined brief. Of `keel board` the fence allows `push`, `list`, `find`, `show` and
`delete` only (the store holds delete to the house's own card); `open`, `new`, `close` and
`restore` are refused there as well as by the store.

## Deleting a board

A board that can only
be closed stays in every list, so there is a delete (lane BD), and it is a
TRASH, not an erase: every delete, by anyone, is restorable by the user for 30 days.

**A delete is a MOVE, not a flag** (BD-1). `keel/boardtrash.py` moves `state/boards/<b-id>/`
whole to `state/boards/.trash/<b-id>/`, with a `deleted` block on its record: `at`, `by`
(`you`, the card id, or `the talker`) and the `actor`. That keeps every reader simple:
`boards.records` walks `state/boards/` and never matches `.trash`, and `boards.read_record`
opens `<b-id>/`, so the list, the search (both `find` and the deck's), a card's boards and
its stacks, the live board and the voice gateway's receipt (`GET /api/boards`) all stop
seeing it without one of them being told. A `deleted_at` field would have had to be checked
by every one of those, and the one that forgot would show a deleted board. Reading a deleted
id is refused BY NAME ("b-006 is in the trash, restorable for 30 days: keel board restore
b-006", `boards.DELETED_MARK`), which is what lets an embed, the lint and a link tell "the user
deleted it" from "it never existed".

**Who may delete** (`boardtrash.may_delete`), one rule for the verb and the action alike:

| Caller | May delete |
|---|---|
| a house (`KEEL_CARD`) | only boards whose source is its OWN card |
| Harbor (`--talker`, `KEEL_TALKER`) | only its own talker boards |
| the user: the deck's own tap, or `KEEL_TOKEN` matching `state/human.token` | any board, one or a whole stack |
| anyone else, including a bare terminal without the token | nothing: refused the way `--actor human` is |

A stack is refused WHOLE when one of its boards is not the caller's. **Restore is the user's alone**
(`boardtrash.restore`): a house or Harbor that deleted by mistake asks the user.

**The live board.** A source's live board is its newest open board in `state/boards/`, so
deleting it clears it as live by leaving: the next push continues the next newest open board
of that source, or starts a new one when there is none. The delete's answer says so
(`live_cleared`). A restore leaves `updated` as it was, so a restored board goes back where
it stood rather than taking over from a newer one.

**The purge** is the drain's upkeep (`drain.board_trash_upkeep`, every pass), never a
request: a board deleted more than `boardtrash.KEEP_DAYS` (30) days ago is removed, and
`<b-id>.purged` stays behind so `next_id` never mints that id again (an embed or a link that
still names it must not open somebody else's board). A delete stamp it cannot read is kept.
A card board's file copies live in the card's own `board-files/` and stay with the card; a
talker board's `files/` go with it.

**Backup** (BD-4). The trash is under `state/`, so the `keel` set carries it until it is
purged, and a restore from the archive brings the trash back with it
([the backup](85-backup.md)).

**Embeds** (BD-2). A plan or an outcome that embeds a deleted board draws a small "board
deleted" placeholder, with who deleted it and Restore for the user, instead of an error
(`planroute.decorate` puts a `deleted` block on it); the lint's C4 finding for that id is a
WARNING, not an error, so a card at its gate is not refused because of something the user did. An
id that never existed is still an error.

**The confirm names where it is used** (BD-2). Before deleting, the deck asks
`GET /api/boards/uses?ids=...` (`keel/boarduses.py`): the plan and outcome of every open
card, and every card touched in the last 14 days, parsed by the plan format's own parser for
a ```board block naming the id. The answer is `{"uses": ...}`, the plans and outcomes that name each id.

## Files, both ways

A `path` attachment is a real file. The rule that makes that safe is one sentence: **the
store never opens a path a push named.**

**From the house to the user.** The process that HAS the file reads it. `keel board push` walks
its own ops first, and for each `path` op reads that file under the roots it is allowed to
read (the card's own directory, and the working directory it is running in, which for a
house IS its worktree; for the TALKER, its own folder `talker/` and nothing else), then
stages the bytes for the store in process (`boardfiles.attach`).
The store keeps a COPY under a name it generates (`<fingerprint>-<basename>`) in
`state/cards/<id>/board-files/`, records it in `board.json`, and the row's **Download** is
an artifact token minted for that copy ([the deck](40-deck.md) mints them the same way for a
plan or a context image). The `path` op keeps the original text only as the label the user reads.

| The rule | Where it is held |
|---|---|
| Resolved BEFORE it is contained, so a symlink out of the worktree is refused rather than followed | `boardfiles.read_local` |
| The talker reads only under `talker/`, and a relative path is read from its working directory when that is inside `talker/`, else from `talker/` itself (C2) | `boardfiles.local_roots`, `boardfiles.local_base` |
| Never a credential, by the deck's own denylist | `artifacts.denied`, the same list the artifact route applies |
| At most 16 MB, and at most 60 files on one board | `boardfiles.MAX_BYTES`, `boardfiles.MAX_FILES` |
| A push whose file could not be read draws NOTHING | `boards.carry`, on the pushing side, where it can still be fixed |
| A `path` op that arrived with no bytes is a metadata row with no download under it | `boards.take_file` |

The copy outlives what it came from: a worktree that is reaped afterwards leaves the board
showing the file it showed at the time, which is what makes a board a record.

**From the user to the house.** `POST /api/board/<id>/inbox` is the segments' upload route
([segments](30-segments.md)) CALLED rather than copied (`boardfiles.accept_upload`): the same
same-origin rule, the same three content types checked against the file's own magic bytes,
the same 10 MB cap, the same generated name, the same fingerprint de-duplication. The file
lands in `state/cards/<id>/inbox/`, a `path board` op is pushed `from you`, and the CARD gets
a note naming it, because a note is what a house reads at its next turn and no house watches
a board.

**The ceiling.** A board takes a 16 MB file and the artifact route serves 8 MB, so
`artifacts.cap` raises the limit for a board's own directories, decided by where the file
sits and never by anything a request says.

## Drawing from inside a spoken answer

A house in a voice conversation cannot run `keel board push`: it is mid-sentence, and its
shell is not where the conversation is. So it draws by writing the lines in a FENCED BLOCK
whose language is `board`, inside the answer itself:

````
Here is how the pass works:

```board
node card box "A startable card"
node drain server "the drain"
edge card -> drain "claimed"
step card "The drain claims it for this host"
```

That is the shape of it.
````

| Where | What is done with it |
|---|---|
| A streamed turn (the user is connected, `keel/sentences.py` is cutting the answer) | the fence leaves the cutter as its own event the moment it CLOSES, and `keel/boardpen.py` pushes the body, so the board has it before the sentence about it is spoken |
| A one-shot turn (the phone Harbor's one question, the ask box) | there is no stream to cut, so `sentences.board_blocks` takes the same blocks out of the finished answer and pushes them |
| **Harbor's own turn**, through the voice gateway | the same reading, through the same pen, and the push is `keel board push --talker` (below) |
| Any of them | the block never reaches the user's ear, and one sentence built from the push REPORT stands in for it, once per answer (below) |

It is a `boards.push` and nothing else: the same grammar, the same caps, the same
skipped-line rule, the same store, with the WRITER as the caller. A block arriving this way
can do nothing its writer could not do from its own shell, which is what makes the pen
safe.

### What the user hears is the push's report

**The line is built from what the push answered, never before it** (C1, 2026-09-23). The
cutter used to speak "I have put that on the board." the moment a board fence CLOSED, and
the pen counted any push that did not raise as drawn, so a push where 21 of 27 lines were
refused (b-003), or none at all, was announced as drawn: the exact thing B19 and B22 forbid.
Now every push answers with its counts (`accepted`, `skipped`, `reasons`, summed over every
board it touched), `keel/boardpen.py` turns that into a REPORT, and the line is the report's:

| The report | What the user hears |
|---|---|
| `drew`: every line landed | "I have put that on the board." (nothing about a walk until narrated walks exist) |
| `partial`: some lines were refused | "I put that on the board, but 21 of 27 lines did not land: <the first reason>." |
| `refused`: nothing landed, or the push raised | "I could not put that on the board: <the reason>." |
| `repeat`: the store already had it | nothing: it IS on the board, so it is not news |

The reason is said in plain words (`boardpen.said_reason`: a file that is not there, a file
outside what may go on a board, past twelve nodes), with any path taken out. On a streamed
turn the pen answers each closing fence with the line its report earns and
`keel/converse.py` speaks it as a part; on every path the pen's `take` ends the answer with
the same line, so the gateway's check of what was spoken against the final text agrees.

**The model's own claim is stripped** from an answer whose push did not land cleanly: a
sentence saying it drew, or that something is on the board, is taken out of what is recorded
and, on a one-shot turn, out of what is spoken (`boardpen.strip_claims`). On a STREAMED turn
it has already been heard, so the spoken final keeps it and the report line after it says
what really happened: taking it out would make the gateway's spoken-versus-final check see a
divergence and say the whole answer again.

**What did not land is written down and carried.** A house's pen leaves a `board report:`
note on the card, and `keel converse` puts that note into the NEXT turn's framing
(`converse.pending_report`: the note just before the newest exchange, so exactly once), with
the raw reason, so the house repairs it in its following answer. `keel converse` also
answers with the report as `board`, and the gateway writes a `draw-failed` record into its
transcript. Harbor's own pen (`voice/harbor_voice/drawing.py`) writes the same
`draw-failed` record with its turn, and leaves the report in `state/voice/board-report.txt`,
which the next Harbor turn reads once and frames.

### A drawing is never explained live (N7)

**Once an answer holds a board block, only the prose BEFORE the block and the report line
are spoken.** The rest stays in the transcript and on the card (the pen's `written`). Only a
block whose push REPORTED ends speech (drawn, in part, or refused): an empty block, or one the
store already had, silences nothing. The pen is the one that knows, so it is mechanism there,
in two places: on a streamed turn the pen is `silenced` once a closing fence reports and
`converse.events_into` drops every later part, and the pen's `take` builds the spoken text
from the prose up to the first block that reported (`sentences.split_boards`) and the
report. On Harbor's path the rest is written to the gateway transcript as an
`answer-written` record, and a typed ask shows the whole text, because it is read. Where the whole answer is known (a one-shot turn,
Harbor's turn, the ask box) the lead is capped to two sentences (`sentences.first_sentences`).
On a streamed turn the lead is spoken sentence by sentence as it arrives, before anyone
knows a block is coming, so it cannot be recalled and is not capped; the framing asks for
one or two sentences before the block instead.

A **code** fence is untouched by all of this: it stays in the answer where the user can read it.

### Harbor draws too, and the same way

**A house or the talker pushes.** If only a house can draw from inside an
answer, the gap has a shape: asked out loud to draw something on the board,
Harbor reads "a house pushes", answers "a house draws on it, not me, I'll
card it", and files a card (c-421). It has the verb and the memory saying so; what it lacks
is a path from a fenced block in a spoken answer to a push.

Harbor's answers reach the user through the gateway (`voice/harbor_voice/harbormsg.py`), so that
is where the block is lifted, by `voice/harbor_voice/drawing.py`:

- **The reading is the house's reading, literally.** It imports `keel/boardpen.py` and hands
  it a source of `talker`. There is no second parser, no second dedupe rule and no second
  sentence. That import crosses the interpreter boundary and is one file deep, exactly as
  `harbor_voice/index.py`'s is: `boardpen` imports `sentences`, `sentences` imports `hashlib`
  and `re`, and the dependency still runs one way (`keel/` never imports the gateway).
- **The push is the VERB, not the store.** `keel board push --talker --file <ops>`, run as a
  subprocess with `KEEL_HOME` passed explicitly and with `talker/` as its working
  directory (C2): Harbor's turns run there, so a relative path it writes is relative to
  there. Run from the checkout instead, the push says "nothing
  was drawn: <file> is not a file on this machine". Only the verb knows WHICH board this
  checkout writes to: its config decides scratch or live. A gateway that imported the store would write to the local
  one and be confidently wrong, which is the failure `config.KB` already exists to refuse.
- **`run_turn` hands back the RAW answer.** A block whose newlines have gone is no longer a
  block, so the collapse to one spoken line happens after the pen, on what is left.
- **An answer with no block in it is unchanged, byte for byte.** The pen is only reached when
  there is something to draw.
- **From a typed session Harbor uses the verb**, exactly as a house does:
  `keel board push --talker`.

## The ask box

Under the stage, one 56px row: a field, **Send**, and the paperclip that puts a file on this
board. On the phone the field collapses behind an **Ask** button beside the clip. Tapping a
node also puts `About "<label>": ` in front of the field, and the selection clears when the user
sends.

A turn into a house is a whole `claude` and takes tens of seconds, so the question is not
answered in its own request:

| Route | What it does |
|---|---|
| `POST /api/board/<id>/ask {text}` | starts one turn and answers with a TURN ID, in about a millisecond. Same-origin only. A second question while one is in flight is refused (`409`), on the server as well as on the page |
| `GET /api/board/<id>/ask/<turn>` | that turn as it stands: `state` is `running` or `done`, `answered` is the TURN's own verdict and `ok` is only whether the poll was understood |

A **card** board's question is `house.converse` through the deck's own action table, which
is the one-shot `keel converse <card> "<text>"` the phone Harbor runs ([the talker and the
voice](50-talker-and-voice.md)): unpinned, the card's own guards, the exchange recorded on
the card. Its refusals come back AS the answer, because they are sentences written to be
said to the user. A **talker** board's question is ONE HARBOR TURN, WAITED FOR:
`bin/keel-voice ask --wait --json --context "asked from the deck board <b-id>"`, run on the
ask's own turn-id thread (B15), with a 150 second wait because a Harbor turn may take 120.
The reply is Harbor's answer, shown under the box like a house's, and whatever it drew is
already on the board. A busy conversation is one sentence ("Harbor is answering something
else right now; ask again in a moment").

It used to be the bare `ask`, which handed the text to `harbormsg.send`: that starts the
turn on a daemon thread and returns in about 50 ms, so the command exited and killed the
turn mid `claude -p`, and the reply said "It answers out loud", which was false (c-422).
Two things fix it, and neither is a route on the gateway, which has no POST by design:

- **`harbormsg.run_turn_now`** runs the turn in the foreground and returns with the answer
  and how many blocks it drew, writing one `typed-ask` record (`mode: typed`,
  `source: deck`) into the gateway's transcript. `keel-voice ask` calls it with or without
  `--wait`, because a command that returns before its turn is over is the bug.
- **`harbormsg.conversation_turn`**, the conversation's lock across processes: the
  in-process `_TURN_LOCK` and then an `flock` on `state/voice/harbor-turn.lock`, taken by
  the gateway's own worker (waiting up to one turn's length) and by the typed ask (not
  waiting: busy is answered at once). The kernel drops the `flock` with a process that dies,
  so a crashed ask cannot wedge the voice.
- **One deadline each.** The turn's LOST_CONVERSATION retry runs inside the turn's own
  deadline, both locks are waited for against one deadline, and an answer's pushes share
  one 20 second budget, so the typed ask's worst case is `harbormsg.TYPED_WORST` (155 s)
  and the deck waits `boardask.TALKER_TIMEOUT` (180 s) above it, which a test holds. The
  deck starts the ask in its own process group and kills the whole group on timeout, so no
  `claude -p` outlives the lock its parent held.
- **A spoken turn behind a typed one is not a silence.** The gateway probes the file lock
  without blocking; when another process holds it, "Harbor is finishing a typed question
  first." goes out on the PROGRESS channel keyed to that turn (never the opening channel,
  which is claimed once per turn and would take the place of Harbor's own opener), and a
  wait that runs out says a neutral busy line, because the holder may as well be a refine
  or another spoken turn.

The answer shows as a REPLY under the box and never on the board. What was DRAWN is the
board's record; what was said back to one question is not.

## The route, and the three views

`/board` and `/board/<b-id>`, with `?view=diagram|outline|walk`. This is the one deck route
with a PATH of its own, because a board is the thing the user sends themselves a link to. WHICH VIEW
rides in the QUERY, because it is a way of looking at one board rather than another thing to
open, and it is deep-linkable and remembered per board (the URL wins, then what the user last
chose on that board, then the diagram). `/board/<b-id>/<n>` from the frames era still opens
its board: the number is matched and dropped.

`keel/serve.py` answers both shapes with the page; `app/ui.core.js` reads the path
(`boardPath`) and the view, and every other route writes an absolute `/?view=...` so a move
off a board does not keep the board's path in front of it. For the same reason every asset
in `app/index.html` is referenced absolutely.

The rail item is **Board**, after Cards. On the phone the dock keeps its five tabs and the
board is reached from More, the way the Atlas is. The header row carries the board title,
the source chip, a live dot, the node count, the **view switch** (a small segmented control)
and the **Live / Saved** switch.

### Diagram (the default, desk and phone)

The graph fills the stage: ELK, pan and zoom, **Fit**, marks. A node carries a small **count
badge** of what hangs on it, so the diagram says where the detail is without showing it, and
tapping that node opens its attachments: a 320px collapsible panel on the right on the desk,
a drawer across the bottom on the phone. With no node open the desk's column shows what
hangs on the BOARD, and it is SHUT when there is nothing in it: 320px saying "tap a node to
see what hangs on it" is 320px off the stage of a diagram that needs every one. It opens by
itself when the board has attachments of its own, and on a tap; once the user has opened or closed
it by hand, that is the answer it keeps. Tapping a node is also the question (below).

**Following the latest.** When ops append, the diagram is laid out again and a view the user set by
hand is CARRIED OVER; with no zoom of the user's own the fit grows to hold the new node. That is
what following the latest means here: what the user leaned in to look at does not jump away under
the user when the next node lands.

### Outline

The whole board as a readable document, a centred column of at most 880px on the desk and
the full width on the phone: what hangs on the board first, then each group as a heading with
its nodes under it, each node's label, sub label and attachments underneath (steps numbered
across the board, tables as tables, code mono, files as rows), then anything not in a group.
This replaced "All frames", and it is the view that answers "just let me read the thing".

### Walk

The steps in push order, one at a time, with previous, next and a counter, over a compact
diagram with that step's node lit. A step that hangs on the board says so; a step on a node
names it, and tapping that name opens the node in the diagram.

**The step is read where it happens** (Z1, lane Z, 2026-09-24, c-453 with its recorded half
dropped). Voiced walks are not built (the latency does not earn
them): the user looks at a board when it suits them, so the walk has
to read on its own. On the desk the step's words are a CALLOUT that flows out of the lit
node (`app/ui.boardcallout.js`): a card 288px wide at most with "Step n of N" and the node's
name over the words, and a leader line from the middle of the node's facing edge to it.

- **Placed from the laid-out coordinates, never over its node.** `place` takes the node's box
  on the screen (its stage box through the view's one transform), the stage's size, the
  card's measured height and the other nodes' and edge labels' boxes, and tries the four
  sides 24px out. A side that covers less of the other boxes wins, then the one with the
  most room left over. It is arithmetic, and `tests/fixtures/board-callout.js` fuzzes it
  over 4000 shapes: the card is never over its node and never off the stage.
- **Placed again on every pan and zoom**: the board's `applyView`, the one place a view is
  set, calls `follow`.
- **A caption bar at the bottom instead** when the stage is under 480px (`MIN_STAGE`, a
  phone), when the lit node is cut by the stage's edge, when no side has room, or when the
  step hangs on the board. On the phone, outside full screen, the caption is the row under
  the diagram beside the steppers; in full screen it is a bar along the bottom of the stage
  that carries its own steppers (the phone's sheet starts folded) and sits above the sheet's
  head row and `env(safe-area-inset-bottom)`.
- **Full screen walks too**: its stage is told the step, stepping there is a render rather
  than a refit (the layout and the zoom are kept, the lit node is panned into view), and the
  rail keeps only the steppers.
- **The keyboard**: the arrows step (right and down on, left and up back), Escape leaves the
  walk for the diagram. Not while the user is typing, not with a modifier, not off the walk.
- **View state only (B3).** Where the walk is lives in `K.boardState.step` and the callout
  in a layer inside the stage's `data-morph="skip"` host. The module has no request, no op
  and no fold in it, which `tests/test_boardcallout.py` checks, and the fixture steps a
  fake page and asserts the model, the record and the network are untouched.

The plan and outcome pages' embed keeps Open board, to the board's full screen (LP-11), as
the diagram's one button; its folded "What hangs on this board" list, when the board has
steps, opens with a plain link to the same full screen in its walk (`?view=walk&full=1`),
where the callout shows (Z-3).

### Levels: whose board this is

Boards are at house level and at global level, and a board clearly shows which.
A board's source is a card (a house's) or the talker (Harbor's), and everywhere a board is
shown it says which.

- **The source chip**, in the board's header row and on every Saved row: the card id in that
  card's own space colour, or `Harbor`.
- **Saved is grouped, by card and by topic** (C5, 2026-09-23). The level is still the first
  split, **Houses** then **Harbor**. Inside Houses every card is a group, headed by its id in
  its space's colour, its title and its tracker story id when it carries one, the card in
  context first (a card selected on the deck, or the open board being a card's) and the rest
  by their latest activity, newest board first inside each with the live one marked. Inside
  Harbor the boards are grouped by topic (`boards.topic_key`), and a topic with one board is
  just that board. The rows come from `GET /api/boards` (`keel/boardlist.py`), which adds
  each board's card and topic.
- **A group of more than one board is a STACK** (W1 to W3, 2026-09-24), so a card with many
  boards costs one row like any other. Collapsed, the group is one button: its header facts,
  the count ("6 boards"), a live marker when any of its boards is live, the newest board's
  title and age, and two hairline ledges under it for the boards behind. Tapping it (Enter
  or Space from the keyboard; it carries `aria-expanded`) opens it in place into the rows,
  newest first, and the group's header, the same button, closes it again. The card in
  context starts open and every other stack shut; what the user chose for a group is kept in
  localStorage (`keel.board-list.open`, a map of group key to open) and wins over that
  default, and the page draws the defaults when storage is refused. While a search has hits
  every group is open and shows only its hits under a plain header, so a hit is never inside
  a stack; clearing the box brings the stacks back. The find bar runs before stacking, so the
  count is of what passes and a group with nothing left is gone. `stacks` (pure, beside
  `groups`) decides stacked and open; a group of one board is its row.
- **The find bar** (lane FIND, 2026-09-24) is the deck's one find system, the same on Cards
  ([the deck](40-deck.md), "The find bar"). Its words are the search below; its facets are
  Source (house, Harbor, review), Card (with a search of its own once there are many), State (live,
  closed) and Updated (today, this week, this month); its sorts are Latest activity (the
  default), Newest created and Title, which order the groups and the rows inside them; its
  built-in views are Mine this week, From houses, From Harbor and Review boards. The list follows the
  GLOBAL Work / Personal switch: a house board of the other space is hidden until **All
  spaces** is on in the panel, and Harbor's boards, which belong to no card and so to no
  space, are listed in both. Live / Saved stays a page tab, not a filter, and says Saved
  whenever the saved list is what is showing.
- **Review boards are off the list by default** (lane FC, FC-4): a board whose card is a
  review card (`options.review_key`; the row's `card.review`, `keel/boardlist.py`) draws a
  colleague's change, not the user's own work, so the list, its search, its counts and its stacks
  leave it out until **Include review boards** is on in the panel (the same words as every
  Include), or the user picks the built-in view Review boards (Source review, the switch on). It is
  hidden, never gone: the review card's own outcome embed, its Open board and a direct link
  open it as before, and Harbor's and every other house's boards are listed as they were.
- **A finished card's boards are off the list by default** (c-562): a board whose card is at
  stage done or archived (the row's `card.done`, `keel/boardlist.py`) is history, so the list
  leaves it out until **Include done** is on in the panel. Like Include deleted it ADDS them,
  under a **Done** heading after Harbor, grouped by card and stacked like Houses, rather than
  swapping the list. Done is a second reason beside the space: `hidden` names every reason
  (a list), and the find engine (`app/ui.findcore.js`) shows an item only when all of them are
  on, so a done board of the other space needs All spaces and Include done both, and the
  bar's counts are of what is drawn. Harbor's boards have no card and are never done. Hidden, never gone: the card's pane, an outcome embed and a direct
  link still open them.
- **The list's panel grows with its rows** (c-562): it is `panel blist-panel`, not `panel
  grow`, so it fills the screen when the list is short and grows when it is long, and the
  page (`.body`) is the one scroller on the desk and the phone. As a `panel grow` the desk
  pinned it at one screen and the rows ran on below its bottom border (360px of them at
  1440x900 with nine rows).
- **The search** looks across board titles, node labels, what the attachments say, the
  card id, the card title and the story id: `GET /api/boards?q=<words>`, every word
  somewhere on the board, read straight from the board files (no index, one store). A hit
  shows the matching snippet and where it was (a label, an attachment, the story), and it
  opens the board with that node lit, as if the user had tapped it; a place on a node wins a tie,
  because that is the hit that can be lit.
- **Every board can be deleted from where it is shown** (BD-3, lane BD;
  `app/ui.boarddelete.js`): the board page's header has a small menu (Delete board), every
  row of this list has one beside it (rows inside an open stack too, since a button cannot
  hold another button), and a stack's header has its own (Delete all N boards). Each is a
  44px target on the desk and the phone, and each item prints its line from `K.boardTip`
  (`app/ui.tips.js`, `BOARD_TIPS`) under its name, since the phone has no hover. Every one
  opens ONE confirm, the card dialog's frame (a sheet from the bottom on the phone), which
  asks `GET /api/boards/uses` first and draws no Delete button until it has answered: "b-006
  is embedded in c-272's outcome." with Delete anyway, which board was live, and that it goes to a trash for 30 days. Escape or a tap
  outside closes it. **Include deleted**, in the find bar's panel, ADDS the trash under a
  Deleted heading below the list (`GET /api/boards?deleted=1`, read the first time it is
  wanted), filtered by the same facets, most recently deleted first, each row saying who
  deleted it, when, and when it is purged, with **Restore**. It used to be a chip that
  swapped the list for the trash. A link to a deleted board opens a line
  saying so, with Restore, rather than "not there".
- **A card's pane carries EVERY board that card has**, newest first, the live one marked
  (it is the one the next push lands on), each row opening its own board. A card has as many
  boards as it has pictures.

### Full screen

**A toggle in the board header, and `f` on the desk, give the diagram the whole screen** (C6,
2026-09-23; `app/ui.boardfull.js`). The deck's header, rail and dock and the board list are
hidden (`body.board-full`), and the board is one fixed layer the size of the screen: the stage,
and beside it the board's own items (the open node's notes, steps, tables and files, or what
hangs on the board), the view switch and the walk controls.

| | Desk | Phone |
|---|---|---|
| The mechanism | the Fullscreen API on the page, and the same layer; Esc out of the browser's fullscreen leaves the mode too | no element fullscreen on an iPhone, so a FOCUS mode: the same layer at `100dvh`, nothing asked of the browser (also the desk's fallback when the API refuses) |
| The side | a slim rail on the right, 320px open, 56px of icons folded (open, leave, and the three views as letters) | a BOTTOM SHEET over the diagram, never a drawer (P2, I8): its head row always there, opening upwards to at most 60dvh, starting folded, above `env(safe-area-inset-bottom)` |

`/board/<id>?full=1` opens the board straight into this mode, once per load (`fullAsked` in
`app/ui.board.js`): it is what a tap on a board embedded in a plan asks for (lane P round 2).
With no gesture behind it the desk's Fullscreen API refuses, so it is the focus mode.

**Another page may draw a board in its own LOOK** (`model.look`, lane P round 2): the plan
page passes `'plan'`, and `buildGraph`, `drawNodes` and `drawEdges` then ask
`K.boardLooks.plan` (`app/ui.planlook.js`) for a node's size and paint and an edge label's.
A model with no look, which is every board on this page, never asks. `K.boardDraw` also
exports `layoutOnce` (one shape laid out with its readability cost), `drawGraph`,
`outlineView` and `iconShapes` for the plan page.

**A still drawing** (c-732, How work ships, `app/ui.flowpicture.js`): a host with `_still` set
is laid out once, unfolded (`layoutOnce`, RIGHT on the desk, DOWN on a phone), shown whole at
no more than its natural size with the host taking the height that gives (`stillHeight`,
`stillView`), and has no pan, zoom or wheel (`wireGestures` is not wired), so the page scrolls
over it. A model with `inlineLabels` carries each edge's words on the edge
(`elk.edgeLabels.inline`), which keeps a phone's drawing narrow.

The ask row is not in the layer: leave full screen to ask. **Entering or leaving CHOOSES THE
LAYOUT AGAIN** (K-12, 2026-09-24): full screen exists to make the board bigger, so the toggle
forgets this board's kept shapes (`forgetShapes` in `app/ui.boardfull.js`) and every mounted
graph is drawn again at its new size, on the tap and again when the browser reports the
fullscreen change. b-009 at 1440 x 900 is the case: kept from the walk it was a 0.60 row
across an empty screen; chosen afresh it is a clean column at 0.79. So the walk and full
screen may differ in shape, and that is accepted.

**Every OTHER change of the stage's size keeps the shape** (K-5, K-9): the rail folding or
opening, a window resize, the node column, the walk's compact stage. The choice is
remembered on the page state (`B.layouts`, per board and per view, because full screen
builds a new host) and laid out again alone while it reads whole at 0.95 of W4's floor, and
then it is drawn WHOLE a hair under the floor rather than lifted to it and cut (`deskFloor`).
An op that changes the board, the desk becoming the phone, or a kept layout that cannot be
read within the slack chooses again (`keepShape` in `app/ui.board.js`). Laying the board out
afresh on every size change is what once turned b-009 from a clean column into rows looped
round each other; the toggle is the one size change that is the user asking for something bigger.
The full layout uses the same stage, renderers and view switch as the page (`K.boardInner`),
so it is another arrangement of one board rather than a second rendering of it. Checked on a
real phone context (playwright-core, 390x844, deviceScaleFactor 3, isMobile, hasTouch).

### The live channel

An open board page is TOLD when its board grows, on the deck's own event stream
(`GET /api/events`, [the deck](40-deck.md)): `board <b-id> <line>` names the board and how
many lines it has reached, and the page then asks `GET /api/board/<id>?since=<line>` with
the cursor IT holds and appends what comes back. The cursor is a LINE COUNT over `ops.log`,
markers included, because that is the one number both ends can agree on without the deck
holding the server's model or the server holding the deck's. `since=0` is the whole board,
which is also how a saved one is read.

The stream names the one board that is open in its own URL (`?board=<b-id>`), which is what
lets the thread holding it watch that board's `ops.log` for a push made in ANOTHER process:
`keel board push` from a house's shell (or from Harbor's gateway) writes the file and can
publish nothing, and that sweep is what has it land on the user's phone in well under a second. A
push made inside the serve process (a fence in a spoken answer, the user's own drop through the
paperclip) publishes directly from `boards.shut_sitting`.

The five second poll this used to be is still there as the FALLBACK, for while the stream
is shut. Either way it does nothing at all while the tab is hidden, while no board is open,
or on a board that is closed. A board nobody is looking at costs nothing.

A node that arrives while the user is looking at a diagram the user has zoomed into does not disturb it.
The stage's body is marked `data-morph="skip"`, so the deck's render pass never touches what
ELK laid out or what the user's finger did to it, and it never touches that node's own class or
attributes either: the pass builds it empty, so anything else would blank the stage. The
drawing owns that subtree and decides when it is out of date, off the model's `version`. The
bookkeeping (the transform, what has been drawn, what has been seen) lives on the HOST
element rather than on the model, because one model is drawn in two places: the diagram's
stage and the walk's compact graph.

### ELK, and pan and zoom

The diagram is laid out by ELK (`app/vendor/elk.bundled.js`, vendored: `app/vendor/README.md`
names the version and its licence), in the browser, layered: on the desk RIGHT or DOWN,
whichever reads better at that stage (below), for the diagram and the walk's compact graph
alike, and DOWN on the phone.

**A long chain is FOLDED to the stage's shape.** ELK lays a chain of ten nodes out as a
chain of ten nodes: Harbor's "How drawing on the board works" came to 2861 by 104, and no
scale makes that readable in an 862px stage (it was drawn at 0.4, six pixel labels, with its
last node clipped anyway). The desk passes `elk.aspectRatio` (the stage's own width over its
height) with `elk.layered.wrapping.strategy` of `MULTI_EDGE` and 24px of
`additionalEdgeSpacing`, and the same chain folds into rows: 1063 by 563, drawn at 0.934,
whole. Measured against the vendored elkjs 0.9.3, with the DEFAULT cutting strategy, because
`MANUAL` refuses to wrap at all. The phone passes no aspect ratio: it lays out DOWN and
scrolls.

**Only a simple chain is folded** (K2, `shouldFold` in `app/ui.boardlayout.js`): no groups,
or one, and at most two edges between a group and what is outside it. A graph of several
groups folded into rows sends every edge between the groups round the rows, so it is laid
out RIGHT unwrapped.

**Fit is the gate and readability is the choice, and then size** (K1, 2026-09-24). On the desk `layoutBest`
always lays out BOTH, RIGHT (folded or not, as above) and DOWN; two ELK runs on at most
twelve nodes is milliseconds. Among the ones that can be read whole at the readable floor, it
draws the one with the lowest readability cost, and between two within half a point of each
other the one drawn bigger (K-14). `readability` in `app/ui.boardlayout.js` is a pure
function computed from the laid-out result:

| Part | What it counts | Weight |
|---|---|---|
| outside | edges routed AROUND the drawing: some point of the route further outside the box around its two ends than 48px or a fifth of the drawing's longer side, whichever is more (a back edge or a wrap edge taken the long way; a fold's wrap edge stepping one lane past its row is not one) | 30 each |
| crossings | proper crossings between two edges that share no node | 6 each |
| bends | bend points, over every edge | 0.5 each |
| length | total edge length over the drawing's half perimeter | 2 |

When neither can be read whole, the one that shows the MOST OF ITSELF at the scale it is
drawn at wins (`visibleShare`), readability cost breaking a tie within a percent. This
reverses W3's "between two that fail, the bigger drawn wins": on the 1138 x 528 page stage
at 1440 x 900 that rule chose b-009 as a DOWN column at the 2.5 ceiling showing 18% of
itself, over a RIGHT row at the floor showing 99.8%. The earlier
version scored fit alone and tried DOWN only when the folded RIGHT did not fit, so a wide
full-screen stage let b-009's three groups fold into rows with an edge looped round the whole
drawing. The memory tier board (W3's case) is still decided by the gate: folded RIGHT it
could not be read whole, DOWN could. The phone lays out DOWN alone. `tests/fixtures/board-layout.js`
runs this on the real vendored ELK under node, with b-009's shape (`board-b009.txt`) and W1's
chain, and `board-readability.js` pins each part of the cost.
Groups are nested containers with
measured minimum widths and a top padding taken from their title (`GROUP_PAD_TOP`: the
title's baseline, its descent and 8px of air, 32px), so nothing ELK places in a group
reaches its title. The titles are drawn in one layer at the END of the stage, above the
edges, each on a plate of the stage's colour: ELK brings an edge into a group laid out DOWN
through its top wherever it likes, and a title that spans its group (b-009's CLOUD EVENTS
SERVICE) has nowhere to stand aside, so the line passes behind the words instead of through
them. The harness asserts no edge LABEL box meets a title and records the lines that pass
under one. Node boxes are sized to
their own text, measured at the real font on an offscreen canvas rather than guessed from a
character count: a short "A phone" and a long `~/.claude/CLAUDE.md` cannot share one box
size without either clipping the long one or wasting the short one's room. Edge labels are
handed to ELK with their measured sizes. Icons are stroked in `--ink-2`, a marked node takes
`--accent-ink` and its mark's colour. Each node and edge fades in over 200ms as it arrives.

**Pan and zoom is ONE transform on ONE group**, `translate(tx,ty) scale(k)` on
`g.gstage`, never a viewBox rewritten per event: the browser composites a transform and
re-rasterises a viewBox, which is the difference between a smooth pinch and a slideshow.
Every gesture goes through pointer events with `setPointerCapture`, so the mouse, the
trackpad and two fingers are one code path.

| Gesture | What it does |
|---|---|
| wheel, trackpad pinch (a `wheel` with `ctrlKey`) | zoom about the cursor. The listener is `passive: false`, so the page does not scroll under it |
| click and drag, one finger | pan |
| two fingers | pinch to zoom about the midpoint, and pan by the midpoint's own movement |
| a tap that did not drag | opens that node (its panel, and the ask box's subject) |
| double click, double tap on empty canvas, the **Fit** button | back to the fitted view |

The scale is clamped to a quarter and four times the FITTED scale rather than to absolute
numbers, because what "too small to read" means depends on how big the graph was to begin
with.

**The fitted scale is READABLE BEFORE COMPLETE.** On the desk it is the tighter axis while
that is at least **0.6**, which is where a 15px label is still 9px; below that the desk stops
trying to show everything and fits the WIDTH instead, letting the stage be panned down the
rest, which is what the phone has always done, but never past the drawing's natural size:
enlarging a drawing that already cannot be shown whole only hides more of it (b-009's DOWN
column was being drawn at 2.5). It never goes under 0.6 on the desk (with one exception: a
drawing that reads whole at 0.95 of the floor and whose width alone is under it is drawn
whole there, down to 0.57, rather than cut at 0.6) or 0.75 on the phone, and never over 2.5. `Fit` is that same function on the same numbers, so the
button lands exactly where the board opened, and for any layout that can be read whole both
edges sit inside the stage's 8px margin. `touch-action: none` is on `.graphwrap` ALONE, so a one-finger drag
pans the diagram and the page never scrolls sideways.

## A card carries its board

`GET /api/card/<id>` gains a `board` block beside the plan, the output and the context: the
card's LIVE board at the top level (id, title, node and attachment counts), `count`, and
`boards`, every one of that card's boards newest first. `None` when it has never been drawn
on.

## Where it lives

- `keel/boards.py`: the grammar, the one model, the store, the index and the verbs.
- `keel/boardgrammar.py`: `GRAMMAR_VERSION`, the grammar card every copy embeds, and the
  translator for the previous grammar; `python3 -m keel.boardgrammar --write` rewrites the copies.
- `keel/boardpen.py`: a `board` block lifted out of an answer and drawn, for a house and
  for the talker alike. Stdlib-only at import, so the gateway can read it.
- `keel/boardfiles.py`: the files both ways, the staging an attach writes to, and the user's drop.
- `keel/boardask.py`: the ask box's turns, and where a question goes for each kind of source.
- `keel/sentences.py`: the `board` fence in a streamed answer and in a finished one,
  `strip_fences`, and `normalise` (the comparison that makes two readings one push).
- `keel/converse.py`: the pen on a house's turn, and the leave directive beside it.
- `keel/actions.py`: the ten `board.*` action verbs (`BOARD_VERBS`).
- `keel/serve.py`: `GET /api/board/<b-id>`, the inbox and ask routes, and the page routes.
- `keel/deckstate.py`: the `board` block on a card's detail.
- `keel/cli.py`: `keel board` routed to `boards.main`.
- `bin/keel-board-fence`: `keel board` allowed for a confined house.
- `voice/harbor_voice/drawing.py`: Harbor's own turn, read through the same pen and pushed
  with the verb.
- `app/ui.board.js`: the parser, the model, the icons, ELK, pan and zoom, the three views.
- `app/ui.boardlist.js`: the Saved list, grouped by card and by topic and stacked by the sort, the server search the find bar's words start, the done cards' boards added under Done, the trash added under Deleted.
- `app/ui.boardlayout.js`: the readability cost, the choice between two layouts, the fold rule.
- `app/ui.boardfull.js`: the full-screen board.
- `app/ui.boardcallout.js`: the walk's step as a callout from its lit node, the caption bar, the arrows and Escape.
- `app/ui.boarddelete.js`: the delete menus, the confirm that names the embedding documents, the trash behind Include deleted and Restore.
- `keel/boardlist.py`: `GET /api/boards`, every board with its card, and the search; the trash with `deleted=1`.
- `keel/boardtrash.py`: the delete, who may, the restore, the purge, and what an embed of a deleted board shows.
- `keel/boarduses.py`: which plans and outcomes embed a board, for the delete's confirm.
- `app/ui.css`: the route's styles, from the deck's own tokens.
- `app/vendor/elk.bundled.js`, `app/vendor/README.md`: the layout engine.
- `tests/test_boards.py`, `tests/fixtures/board-lines.txt`, `tests/fixtures/board-parse.js`,
  `tests/fixtures/board-model.js`, `tests/fixtures/board-zoom.js`,
  `tests/fixtures/board-fit.js`: both parsers and both models over one fixture, the store,
  the index, the duplicate rule and the zoom arithmetic.
- `tests/test_boardpen.py`: the pen, and each of the three dedupe layers on its own.
- `tests/test_boardgrammar.py`: the card against the parser's tables, every copy against the
  card, the translator, and the framing that carries the card.
- `tests/test_typed_ask.py`: the typed ask on Harbor's board, the lock across processes.
- `tests/test_boardpage.py`, `tests/fixtures/board-list.js`, `tests/fixtures/board-full.js`:
  the list route and its search, the grouping, the stacks and the sorts, and the full-screen
  mode switch.
- `tests/test_boardfiles.py`, `tests/test_boardask.py`: the files both ways, and the ask box.
- `tests/test_boardtrash.py`, `tests/test_boardtrash_http.py`: who may delete, the event,
  delete hiding everywhere, restore, the purge, the embeds, the lint, the confirm's question.
- `tests/test_boarddelete_ui.py`, `tests/fixtures/board-delete.js`: the confirm's words, the
  menus and their lines, Include deleted, the 44px targets. The find bar on this list:
  `tests/test_find.py` with `tests/fixtures/find-ui.js`, and `bin/keel-find-audit` in a browser.
- `tests/fixtures/example.board`: the worked example, parsed by the tests.

## How to change it

- **A new op or a new icon**: `keel/boards.py` and `app/ui.board.js` in the same commit, a
  row in `tests/fixtures/board-lines.txt`, and the table above. The vocabulary test fails
  on one side alone.
- **A new attachment kind**: the same three, plus a renderer in `app/ui.board.js` (one
  function, used by the node panel and the outline alike) and its styles in `app/ui.css`.
- **A new view**: `VIEWS` in `app/ui.board.js`, its builder, its styles, and the test that
  says the deck knows three views and no others.
- **Anything about the spoken side**: `keel/sentences.py` decides what a fence IS and says
  nothing about boards beyond its language; `keel/boardpen.py` decides what is done with it,
  for a house and for Harbor alike. Keep it that way: the cutter is pure, and that is the
  whole of its testability.
- **A new verb**: `boards.HANDLERS`, `actions.BOARD_VERBS`, a test, and the verb table above.
- **Anything about a file**: `keel/boardfiles.py` alone. `keel/boards.py` folds the record's
  `files` map and opens nothing itself, which is the property to keep: the store must never
  become the thing that resolves a path an agent wrote.
- **Anything visual** is verified by rendering it, at 1440x900 and at a real 390x844 phone
  context, by the audit `<install>/history/tests/live_deck.md` records.
