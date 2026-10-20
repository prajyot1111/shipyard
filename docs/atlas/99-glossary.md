# Glossary

Terms used across Keel, alphabetical. Each entry is one sentence; follow the link for the
mechanism.

**Adapter**: the only directory that knows about an employer, teaching Keel how to cut a
worktree, brief a house and publish an outcome ([the work adapter](60-work-adapter.md)).

**Archived**: `options.archived` on a card, which takes it out of every list, every gate
and the drain's reconcile without deleting it.

**Ask**: a JSON file a segment writes to say it needs something done, which the fetch role
turns into a restricted errand card ([segments and fetch](70-segments-and-fetch.md)).

**Ask box**: the row under a blackboard's stage. What the user types there becomes one turn into
that board's own house, or a handoff to Harbor on the talker's, and the answer shows as a
REPLY under the box rather than on the board ([the board](45-board.md)).

**Attachment**: one thing hanging on a blackboard's node, or on the board itself: a note, a
step, a table, a snippet or a file. Attachments append and are never edited, and steps are
numbered by push order across the whole board ([the board](45-board.md)).

**Attended versus autonomous**: a card's `autonomy`. Attended stops at the plan gate;
autonomous writes the plan and carries on. Both end at the outcome gate.

**Backlog**: derived, not a stage. A card that has sat at its outcome gate longer than
`backlog_days`, which takes it out of Attention but not out of `kb list --backlog`. The
days count from when it got there or from the user's last own action on it since (c-673).

**Builder**: Bosun on an install, the one builder (c-621): it builds `[builder] repos` (packs
and the personal repos the user lists) from its own clones, as the user in auto mode or bypass
(`[builder] mode`), one hook keeps it out of live checkouts, and it lands nothing without
the user's Approve outcome. An install has no superuser; the superuser (`[builder] superuser`) is the legacy builder of Keel
itself, which started only as its own Unix user; that mode is retired (c-648), so it does not
start today ([Bosun](96-bosun.md), "The builder").

**Blocked**: a flag (`blocked_reason`), not a stage. The card keeps where it was and shows
in Attention with what the house last said.

**Blackboard**: the surface a house or the talker draws on, and its deck route. It pushes a tiny
LINE LANGUAGE and Keel renders it; what it drew is saved as a record and is findable later
([the board](45-board.md)).

**Board**: two things, and the word alone means the first. `state/board.db`, the SQLite
file that is the only state Keel keeps. A **board** with an id like `b-004` is one
blackboard, saved under `state/boards/<b-id>/` as a record of something a house showed the user.

**Bosun**: Keel's builder, one Claude Code session running on this machine,
with its own page (`/console`) and memory (`bosun/memory/`); in builder mode it builds the
personal cards that have a repo. Its `kb` is actor `bosun`, never the user ([Bosun](96-bosun.md)).

**Card**: the unit of work, and the whole record of it ([cards and gates](10-cards-and-gates.md)).

**Contract**: `etc/house-contract.md`, the under-60-line document prepended to every house
brief. It explains; the mechanisms enforce.

**Deck**: the web surface, served by `keel serve` ([the deck](40-deck.md)).

**Claim**: `kb claim`, a drain's bookkeeping that names the host a card's house starts on;
the claim that commits first wins ([the drain](30-drain.md), "Claims and relays").

**Derived**: a fact computed from a card on every read rather than stored, so nothing has
to be kept in agreement (`keel/views.py`).

**Discussion**: a plan sent back with `stay`, which keeps the gate open and holds the
house in a poll and reply loop on the surface. The one time a house waits on a human.

**Drain**: the loop that starts houses and reconciles them against the harness
([the drain](30-drain.md)).

**Drop in**: entering a card's house yourself, at any stage including `done`: `claude attach`
joins a live house, `claude --resume` reopens an exited one in its placement. The deck cannot
open one from a server, so it hands back the exact command (`keel/dropin.py`).

**Errand**: a card with no `repo`, which runs restricted in the card's own directory with
no worktree.

**Frame**: RETIRED, 2026-09-21. A board was a filmstrip of frames and is now ONE model:
one diagram with attachments hanging off it, seen three ways. A second picture is a second
BOARD (`board new`), not a second frame. `frame` is refused by name in the grammar, with
the reason saying what to write instead ([the board](45-board.md)).

**File attachment**: an attachment that carries a real file (a `path` op). The push that
names it carries the bytes, the board keeps its own copy, and the row has a Download; a file
THE USER drops on the board is the same row `from you`, landing where the card's house will find
it ([the board](45-board.md)).

**Event stream**: `GET /api/events`, the deck's live channel. The page opens one and is
told what changed (`state`, `card`, `board`, `ping`) rather than asking every five seconds;
the poll is what runs only while the stream is shut ([the deck](40-deck.md)).

**Gate**: an open question for the human. Plan (attended, at `planning`, with a plan) and
outcome (at `review`). A gate is a stage, so answering it anywhere answers it everywhere.

**Harness**: Claude Code itself, and the only thing that knows whether a session is alive.
`keel/harness.py` is the only module that runs it.

**House**: one background Claude Code session working one card ([houses](20-houses.md)).

**`houses_max`**: how many houses this machine runs at once. A card at `review` holds no
slot, and neither does a house idling at its open plan gate. A `[keel]` key
([the drain](30-drain.md)).

**Memory gate**: the drain starts and resumes nothing while this machine's available memory
is under `memory_floor_mb`.

**Browser slot**: at most `browsers_max` houses whose card declares `options.browser` run
at once.

**Import**: `shipyard import <snapshot>`, an existing Keel brought from a `keel` backup snapshot into
an install once, every path under the old state roots moved and what a one-machine Keel does
not use cleared ([import](87-import.md)).

**Injected versus recall-on-demand**: memory loaded into every session versus memory the
agent has to follow a pointer to reach.

**Integration branch**: the branch a repo's approved outcomes land on instead of the branch its checkout runs (`[integration]`; Keel's is `next`); main moves to it only on the user's deploy ask.

**`kb`**: the board CLI, `bin/kb`.

**Lavish**: the tool that renders a plan as an annotatable surface. The deck proxies it and
revives it when a person asks for a surface and nothing answers.

**Live strip**: the one line on a live card saying what its house is doing now (status,
turn, last tool, todos, jobs, each with its age), read from the harness only while a
deck watches and held in memory, never on the board
([the deck](40-deck.md)).

**Morph**: how the deck draws. A renderer builds a fresh tree and `K.morph` writes only
the difference into the live one, matching children by `data-key`, so the live node never
leaves the document and nothing the DOM was holding for the reader is thrown away
([the deck](40-deck.md)).

**Needs you**: derived. An open gate, a blocked card or an open segment notice, never a
backlog or archived card. It is what Attention and `kb needs-you` show.

**Nudge**: the `Stop` hook's `block` answer, which makes a session continue its own turn
when it stopped at `building` without moving the card. At most twice.

**`options`**: the JSON column on a card holding everything per-card the adapter's
`options.json` declares.

**Parent and after**: the two fields that make a child card. `parent` names the card it was
split from, `after` the sibling it waits for.

**Provider**: an adapter executable printing the rows of an extra deck route, with each
row's lane and verbs decided in the provider and never on the page.

**Revision (`rev`)**: what the state document and a card's detail carry as an `ETag`. The
page sends it back and a match is a `304`, so nothing is fetched and nothing is drawn when
nothing changed. One function computes it, and it is read off what the board CONTAINS
rather than off any file's mtime, because a read must never move it ([the deck](40-deck.md)).

**Relay**: a request written as an event and carried once by the drain of the host it is
addressed to (`kb relay --to`): a held tap (resume, stop, close-idle, start) or a `land`
([the drain](30-drain.md)).

**Record**: `state/cards/<id>/context.md` and its `assets/`, written while the work happens,
which is what lets someone drop in after the worktree is gone.

**Segment**: a self-contained thing that gathers data on a schedule and shows it, bounded
to static files ([segments and fetch](70-segments-and-fetch.md)).

**Review card**: a card (`kind: review`, `options.review_key` `<repo>:<number>`) that reviews
a colleague's pull request: filed in the work inbox by the review fetcher, started by the user's
Review tap, run in the review pool with the review core in peer mode, and posted on the pull
request by the user's Approve of its outcome (the review kind); Re-review is a new round on the
same card ([the work adapter](60-work-adapter.md), "A review card").

**Review pass**: one run of Keel's pre-gate review on a house's change: the reviewer's
findings and the verifier's verdicts on them, one entry in `review-findings.json`. It is
open until verified; the verifier closes an open pass before any fix check, and a closed
pass writes the stamp, a head per worktree ([houses](20-houses.md), "The review step").
Not a batch at shipping below.

**Fix check**: the verifier alone on what changed since the stamp's heads (`prep --since`),
confirming a closed pass's fixes and moving the stamp; once called a delta check.

**Batch (at shipping)**: the review on a shipping card's pull request, told to the card's own
living house after 5 quiet minutes: comments, reviews and failed checks. The house records a
verdict per item, and the user's Ship posts the replies they keep. It replaced the review round,
which rotated a fresh session and ended at the user's gate (c-600; [the drain](30-drain.md),
"Shipping").

**Ship**: the user's one action at shipping: push the house's commits, mark a draft pull request
ready, post the replies they kept, once ([cards and gates](10-cards-and-gates.md), "Review at
shipping").

**Verdict**: the house's judgement of one review item at shipping (`kb verdict`): valid, not
valid or deferred, the reasoning, and a code change or a reply.

**Shared house key**: `~/.config/keel/credentials/house-key`, 0600, minted by `shipyard init`.
It is what the house tier checks on loopback, and Bosun's key is derived from it
([the talker and voice](50-talker-and-voice.md), [Bosun](96-bosun.md)). Distinct from
`<state>/house.key`, which is this machine's own and may never arrive through a proxy.

**Shipping**: the stage of a work card whose pull request is ready, between `review` and
`done`: its house's work was approved, the house lives on to answer review, and the drain
watches the pull request until it merges ([cards and
gates](10-cards-and-gates.md)).

**Source** (of a board): the card a board belongs to, or the talker. Each source has one
LIVE board at a time, and that is the one a push appends to; it is also what a board's
LEVEL is read from ([the board](45-board.md)).

**Space**: `work` or `personal`. It picks a `CLAUDE_CONFIG_DIR`, a set of repos and an
adapter, and it is the whole credential boundary. It is immutable on a card. The `console`
space was Bosun's board until c-593 retired it; its old cards stay, archived
([Bosun](96-bosun.md)).

**Stage**: `inbox`, `assigned`, `planning`, `building`, `review`, `shipping`, `done`. Three
writers move it: the human, the drain, the house (a house never moves a shipping card).

**Startable**: `assigned`, not blocked, and its `after` card at `review`, `shipping` or `done` (only `done` when that card's repo lands on an integration branch).

**Stage** (of the board route): the panel the diagram is drawn in, with its own header and
its Fit control ([the board](45-board.md)).

**View** (of a board): one of three ways of looking at one board, deep-linked as
`?view=`: **diagram** (the graph, with a tapped node's attachments beside it), **outline**
(the whole board as a document) and **walk** (the steps one at a time over a compact
diagram) ([the board](45-board.md)).

**Level** (of a board): whose board it is. A board's source is a card, so it is a HOUSE's,
or the talker, so it is HARBOR's. Every place a board is shown says which: the source chip,
the two sections of the Saved list, and the card's own pane ([the board](45-board.md)).

**Talker**: Harbor, the long-lived session the user speaks to from a phone. It files cards and
reads the board and never does work ([the talker and voice](50-talker-and-voice.md)).

**Token**: two different things. `state/human.token` proves a write is the human's, which is
what makes `kb approve` the user's alone. An artifact token is a path plus an HMAC, which is how
the deck names a file without letting the browser name a path.

**Topic**: a free grouping word on a card, inferred by the composer and settable, that the
deck groups and filters by.

**Tracking card**: a card with children. Its stage is derived from theirs, it has no gate
of its own, and it is never startable.

**Worktree**: a git worktree a house works in, cut by the adapter (work) or under
`state/worktrees/<id>` (personal).
