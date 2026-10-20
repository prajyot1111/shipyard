# Cards and gates

A card is the unit of work and the only state Keel keeps. It carries what to do, who may
do it, and where the record lives. Its stage IS its gate: an attended card at `planning`
with a plan is the plan gate, a card at `review` is the outcome gate. Approving is a stage
move, so a gate answered anywhere is answered everywhere.

## The record

SQLite, `state/board.db`, five tables (`cards`, `events`, Bosun's `requests` and `asks`, and `holds`, Bosun's voice hold in `keel/bosunhold.py`), WAL mode, every write in a transaction. A column
added after the first schema is listed in `board.MIGRATIONS` with its `ALTER TABLE`, and
an older board migrates when it is opened. The indexes are a second script
(`board.INDEXES`) run after those alters, because an index on a column a migration is
about to add cannot be created on the file that still lacks it.

`cards`: `id`, `space`, `title`, `brief`, `autonomy`, `repo`, `model`, `stage`,
`blocked_reason`, `session_id`, `plan_ref`, `output_ref`, `parent`, `after`, `from`,
`topic`, `options`, `created_at`, `updated_at`, `rank`. `after` holds one or more card ids
separated by commas (`c-311,c-313`); `rank` is the card's place in the queue, null until
`kb next` moves it ("The card tree", below). `from` is a SQL keyword, so every generated
statement quotes every column name (`board.quoted`).

`events` is append-only: `card`, `at`, `kind` (create, set, stage, note, hook, session,
resume, block, unblock, split, approve, claim, relay, carried, correct, mark, reply,
request, ask, intervene, wake, tell, grant), `actor` (human, drain, house, hook, serve, fetch,
import, voice, bosun, doctor), `text`, `data`. A `request` event's `card` is a request's id
(`r-N`), not a card's. `intervene` is one of Bosun's repairs, signed with its why,
`wake` is the drain telling Bosun a house auto mode paused, or what a `tell` asked, and
`tell` (c-734) is the user's tap that Bosun is to hear of: a card the page filed for it, or
a gate tap on a card it builds ([Bosun](96-bosun.md), "Repairs", "A paused house" and
"Telling Bosun"); what actor `bosun` may write at all is `keel/authority.py`. `grant`
is history: the user's grant over a driven card's gates, retired with driving in c-593. An old
card may still carry `options.driver` and `options.grant`; nothing reads them.

`requests` holds Bosun's requests (`r-N`, c-520): who filed it, the card it is about, its
line, the key that folds repeats, and how it ended. It is not a card; [Bosun](96-bosun.md)
says how it works.

Three fields carry most of the meaning:

- **`space`** is `work` or `personal`, immutable after create. It picks the config dir,
  the repos and the adapter. It is the whole credential boundary.
- **`autonomy`** is `attended` (stop at the plan gate) or `autonomous` (write the plan,
  do not wait). Autonomous is the default, except on a card that opens a new project.
- **`options`** is one JSON column. Everything a per-card settings form offers lives here,
  and the space's adapter declares the schema in its `options.json`, so the engine never
  learns an employer's vocabulary.

## Where a card's fields come from

Every card is filed through one resolver, `keel/cardspec.py`, and `Board.create` is where
it runs: the deck's composer and the voice capture reach it through `kb create`, and so do
the talker and a house's follow-up; the recurring filer calls `create`
directly and `kb split` resolves each slice the same way. Nothing files a card around it.

Four card fields are tracked, `repo`, `model`, `autonomy` and `topic`. Each is filled from
the first layer that has it, and the layer is written to the card's own
`options.provenance`:

| Provenance | Where the value came from |
|---|---|
| `stated` | the creator gave it |
| `assumed` | the creator gave it and marked it a guess (`kb create --assumed repo,topic`), or a later `kb set <id> repo=<key> --assumed repo` did (only the `voice` actor, the capture's refine, and never over a `stated` field; D-3, D-13); a guess set that way is not recorded as a correction, and the user's own later change of it is |
| `inherited` | the card it came out of (`--from`), else its parent |
| `space_default` | the space's own: `[spaces.<name>] model`, `autonomy` and `topic` (c-633: `autonomy` counts only when the config gives it or it differs from the default) |
| `keel_default` | Keel's own: `[keel] model` (opus by default, `models.KEEL_MODEL`), autonomous, no repo, no topic |

**No card leaves create without a model** (c-434). A card with none used to reach
`claude` with no `--model`, and `claude` then runs on the ACCOUNT's default: c-272 ran five
days on Fable that way. The model is checked where it is typed, too: `kb create --model`
and `kb set <id> model=` take `opus`, `sonnet`, `haiku` or `fable` (each also with `[1m]`)
or a full `claude-...` id, and refuse anything else, an empty value included, since an
empty model is the hole this closes. A follow-up filed with `--from <id>` inherits its
source's model, repo, autonomy and topic, as a slice always did from its parent.

A space's `confirm` list names the fields that may never pass silently (personal: `repo`,
`model`; work: `repo`, `autonomy`, `design_doc`, `base`, `tracker_mode`). An option key on
it is tracked as well, but only its provenance is written: its default stays the option
sheet's, read where it is used, and is never copied into the options.

**A slice starts as its parent would** (c-760, `cardspec.taken`). A card with a parent and
no `--from` (a slice of `kb split`, or `kb create --parent`) also takes the parent's
options, by these rules:

- Only the keys the space's option sheet declares as stored in `options`, and only a value
  the parent STATED, which means a value present in the parent's own options. A value the
  parent never held is not copied: the default stays the sheet's. What the slice states
  itself wins, an empty value included.
- A parent filed from the deck's card form holds every row's value, the form's defaults
  included (the form writes each one), so all of them count as stated, and the board
  already records them so. A slice that copies one is pinned against a later change of the
  sheet's default exactly as its parent is pinned. A value equal to the default is not
  skipped: the owner may have chosen it on purpose, and nothing on the card says otherwise.
  A parent filed with `kb create` holds only what its creator gave.
- A row's own `when` is asked on the slice, so a slice that states "no ticket" does not
  carry the parent's ticket rows. A `when` the board cannot read refuses the split or the
  create, naming the row and the space ("the work sheet's row base has a `when` the board
  cannot read: ..."); the row is never skipped silently.
- Every key taken this way has the provenance `inherited`, on the confirm list or not, so
  an inherited row can be told from one the slice stated, and a later `kb set` of it is
  recorded as a correction like any value that was not stated. The readback says
  "inherited from c-12" for it as it does for the four fields: a confirm key with its
  value in the line, a row off the confirm list by its label in that group ("... story
  mode and unit tests inherited from c-12"). `kb split` says each
  slice's readback on stderr and carries it as `readback` in its `--json`, as `kb create`
  does, and under it the block of a slice that was filed held (below).
- Four kinds of row stay behind. The parent's own (`cardspec.OWN`: its ticket reference,
  branch, worktrees, claim, app link, peak memory). Every option a creator could not have
  stated at create: the board hands its own lists to the resolver (`Board._resolve`:
  `HIS_AT_CREATE`, which holds the stack answers and the flow and shipping grants, the
  worker, and `RESERVED_OPTIONS`), so a new one is covered by adding it to the board's
  constant and nowhere else, and a split comes out the same whoever runs it. Free
  text written for the parent (a `textarea` row, such as a guidance steer). A row its
  pack marks `"inherit": false` ([options.json](60-work-adapter.md)). Nothing that is not
  a sheet row travels at all, so none of the parent's bookkeeping can.
- `kind` travels: a bug or chore card's slices are bug or chore slices, which is what
  names their branch type. Two kinds do not (`cardspec.OWN_KINDS`): `research` and
  `review` say what the PARENT was for, and a slice of either is an ordinary card on the
  sheet's default kind (a research slice would open no change). Nothing at a split can
  state a slice's own options: `kb split --slice` takes a title, a brief, what it waits
  for, `repo=` (its own repos, "Big cards" below) and `stack=`. A slice with options of
  its own is filed with `kb create --parent
  <id> --option key=value`, and after that the owner changes a slice's kind (`kb set`,
  with the token), since `kind` is the owner's to change once a card exists.
- A parent linked to one existing ticket hands its slices the mode and not the ticket. A
  slice cannot start like that, so it is BLOCKED as it is filed (`Board._hold_left_behind`,
  from `cardspec.left_behind`): the split goes through, since the deck's Split cannot
  state a mode per slice, and each such slice's block says no more than is known and the
  two ways on, "story was c-12's own and was not inherited, and this card's inherited
  tracker_mode=link an existing story shows that row. Give this card its own (`kb set
  c-13 options.tracker_ref=<value>`) or state a different tracker_mode (`kb set c-13
  options.tracker_mode=<value>`), then unblock it". The same holds for `kb create
  --parent`, and both verbs say "c-13 is blocked: ..." on stderr under the readback.
- The hold is narrow on purpose, because a `when` is the form's show-this-field rule and
  not a requirement. Only a row that is one of the parent's own artifacts (`cardspec.OWN`,
  the ticket reference) can hold a slice, and only when its `when` picks the row for one
  value (`key == value`, `cardspec.picked_by`) that the slice inherited. A row outside the
  parent's own that a pack marks `inherit: false` never holds a slice (one of the parent's
  own rows holds whether or not its pack also marks it), nor does an owner-only key, nor a
  `when` that only
  rules a value out (`tracker_mode != none` shows the row for every other mode, and a
  slice in a mode that makes its own ticket needs none). A slice that states the mode or
  the reference itself is not held.
- An inherited value that a create-time rule refuses does not travel (`Board._untaken`).
  Each rule answers for its own key and is asked only of a value that came from the parent
  (in the resolved options, absent from the stated ones): a base on a repo that lands on
  its integration branch (`_base_problem`), and the browser on a repo whose CLAUDE.md does
  not say how to run the app (`_browser_problem`). The value is given up, its provenance
  is the sheet's again, and the slice carries one note for it: "base staging was c-12's
  and was not taken: web lands on its integration branch, so a card on it names no base of
  its own". The same list runs at `kb create --parent` and at the split, and a STATED
  value is refused as it always was. A base that is no branch name refuses even when
  inherited: that rule is about the name, whoever gave it.
- An inherited base yields to a stack that stands (`Board._stack_base`, at the split and
  at create alike): a stacked card merges into the base of the card it is stacked on, so
  an inherited base that differs is given up, with the note on the slice ("... this card
  is stacked on c-13, which merges into hotfix") and the same sentence in the split's
  stacking note. The stack check at create runs on what the card resolved to, so a slice
  filed with `kb create --parent --after` and `stack=stacked` is checked on its inherited
  repo and base. That holds for a card that is no slice too: one that takes its repo from
  `--from` and is stacked on a card in another repo is refused at create ("c-13 works in
  api, not in web"), where before c-760 only the stated repo was asked and it was filed.
  It is what `kb set` already refused on the same card. A slice whose approved answer cannot stand (the space does not stack, the sibling
  is research) is left without a choice and keeps the base it inherited.

A follow-up (`--from`) is a different relation, new work that came out of a card, and it
takes the four fields and none of the options. A card with both a parent and a `--from`
is a follow-up.

**The readback is code's.** `kb create` says one line on stderr and carries it as
`readback` in its `--json`: `Filed c-450 in keel, opus, topic boards (repo and topic
assumed)`. It names where the card went, the model, the topic, every `confirm` field, and
in the parenthesis every named field that was not stated, grouped by where it came from.
Every creator says the same sentence because none of them writes it.

**A correction is an event.** A later `kb set` of a field that was not stated, to a
different value, is the user's correction of what was assumed or defaulted: a `correct` event with
the field, the old value, the new one and the provenance it replaced, and the field is
`stated` from then on. It lives in the events table like everything else, never in a second
store, and it is the record c-437's hand fix would have left.

## The stages

```
inbox ──► assigned ──► planning ──► building ──► review ──► done
                   └─► building (autonomous)         │  ▲
                                └──► blocked_reason ─┘  │ (a flag, the stage stays)
                                                        │
                  work card, pull request ready:   review ──► shipping ──► done (merged)
                                                         (its house lives on, answering review there)
```

Exactly three writers move a stage: the human (through the deck or the talker), the drain
(assigned to planning or building, and blocking anything), and the house (building to
review). `planning` and `review` are protected by construction, because idle there is the
definition of waiting on a human. Waiting also costs no pool slot: an idle house at an open
plan gate is not counted against `houses_max` or `reviews_max` (see [the drain](30-drain.md)),
so an unanswered plan never holds up another card's start.

A card at `building` whose house has gone quiet is NOT waiting on a human: it keeps its
stage and its slot while the drain puts the house back, and only after three attempts does
it get a `blocked_reason` that says so ([the drain](30-drain.md), "A house the account's
limit stopped"). A house that really does need the user blocks its own card instead, which is
what makes the two tellable apart. A house that is stopped by KEEL rather than by a question
says so with `kb block --keel`: the same block, with a reason that opens "Keel, filed with
Bosun as r-N", and a request filed in the same write ([Bosun](96-bosun.md), "Requests").

`kb stage` refuses what must not happen: an attended card may not leave `planning` without
an approval, except back to `inbox` or `assigned` (`board.QUEUED`) by the user or Bosun, which
skips no gate (a card started by mistake; never a house, whose card the drain would start
again), `review` needs both a `plan_ref` and an `output_ref`, and `done` comes only
from `review` or `shipping`. Before the move is written, `kb stage review` also holds a
repo card to its pre-gate pipeline (review, verify, preship, risk; [houses](20-houses.md)):
a branch behind its base, an unanswered surviving finding, an unnamed surviving high one or
a Risk below Keel's is refused with the fix. Last, it asks the space's adapter whether the user's
Approve could publish the card (`publishable <id>`, the card on stdin; `adapters.publishable`,
`plangate.publishable_check`, c-551), where the clone and the credentials are: a no is
refused with the adapter's one line, and a check that could not run is refused too, so a
gate never opens on a card whose Approve would be refused. A verified nothing-to-land card
(its record says `change: none` and it has no commits over its base) is let through
whatever host its claim names: `plangate.nothing_to_land` is computed here and skips the
preship first check for it (r-51). The proof is read in the card's own worktrees only
(`plangate.own_tree` and the recorded ones), never in the checkout `kb` runs in, which for
the deck is the live one; a card with no worktree here is unverified and takes the preship
check (c-622). A space
without the verb (personal) is never asked, and nor is a card that has shipped (what its
house commits at shipping is pushed by the user's Ship). The one exception is an open notice (below): it has no outcome gate to pass,
so it is staged `done` from whatever stage it sits at, by any actor, since anyone may file
one (J-1).

### Shipping: a work card's pull request, after Approve

`shipping` (lane SHIP, decisions SH-1 onward) sits between `review` and `done`. A work card
whose Approve outcome published a ready pull request goes there, not to `done`, and it
reaches `done` when the pull request merges. The board decides it from the publish's own
answer (`board.ships`): only an answer carrying `"shipping": true` sends a card to
shipping, so a personal merge, a research card, a tracking card and a declined pull request
still go straight to `done`. `Board._enter_shipping` writes the watcher's record,
`options.shipping`, in the move's own transaction.

Who moves it (`Board._refuse_shipping_move`): nothing reaches shipping by a plain `kb stage`
from review. The other way in is the shipping sync's own move, `Board.ship_from_sync` (`kb
stage <id> shipping --sync`, the drain's or the user's): from `done` or from `review`, with a fresh watcher's record
(its first look is a baseline, so comments already there are not a batch) and the stage
event marked `sync`. From review it publishes nothing, since the pull requests are already
out, and it is refused for a card at review that already has a watcher's record (a review
round, or a declined pull request, at the user's gate). That is what `bin/keel-shipping-sync
[--dry-run]` does (`keel/shipsync.py`, SH-11, run where the work houses are): it hands the space's cards to the adapter's `ship mine`, which lists THE USER'S open pull
requests in every repo, each matched to cards by branch and otherwise by story ([the work
adapter](60-work-adapter.md)). A pull request matching two cards goes to the one that
already records it, else the most recently updated, with a note on the other; one matching
no card is listed and left alone. Each card records `options.prs` (`{repo: {pr, branch}}`,
one per repo; `options.pr` and `options.branch` too when it had none), the worktrees found,
and any repo it did not name (added to `repo` after the primary). When every one of its
pull requests is open and not a draft, a card at done or review goes to shipping; a draft
keeps it where it is; a card already shipping only has its record brought up to date. It
never deletes anything, `--dry-run` prints every decision and writes nothing, and a second
run changes nothing. `bin/keel-prs-backfill [--dry-run]` (`keel/prsbackfill.py`, c-584) is
the one-time fill for a card that recorded its primary repo's pull request only as
`options.pr` (c-573): each card at review or shipping whose primary repo has no entry in
`options.prs` gets `{pr, branch}` there from its own `options.pr` and `options.branch`, with a
note. It reads the board and nothing else (no code host), writes only what is missing, and the user
runs it once, or Bosun does on the user's word. From shipping a card goes only to `done` (merged, or
the user's own move), and only the drain or the user moves it (`board.SHIPPING_NEXT`, c-600): its build
house LIVES ON at shipping and answers review there ("Review at shipping", below), so
nothing sends the card back to building or to the user's gate, and a house has no business closing
its own pull request's card. A card at shipping is at no gate and does not need the user; a card
waiting on it (`after`) may start, as it may for one at review. `options.shipping` is
written only by the drain and the user (`board.SHIPPING_ACTORS`), and no card is filed carrying
the record.

## The two gates

| Gate | Open when | Answered by | What the answer does |
|---|---|---|---|
| Plan | `stage = planning` and `autonomy = attended` and `plan_ref` is set | `kb approve <id> plan [--said "..."]`, the human's token only | Stages `building`, notes what the user said, and resumes the house with the approval prompt |
| Outcome | `stage = review` | `kb approve <id> outcome [--said "..."]` | Runs the adapter's `publish`, then stages `done`, or `shipping` when the publish says its pull request is ready (the house then lives on, c-600); what the user said is noted, nothing is resumed |

An ask card (a segment worker's, carrying `options.drop`) is the one exception at the outcome
gate: its output is folded by the fetcher before anyone looks, so the fold is its approval and
the fetch role stages it `done` itself ([the fold is its approval](70-segments-and-fetch.md)).
It waits at `review` only when the fetcher refused the drop, and the note says why.

With `[keel] plan_pages` on (it ships on) every new plan and outcome is written in the plan
format and read on its own page ([plans on the deck](47-plans.md)), and `options.plan_style`
is not read. With it off, `options.plan_style` (a field of every space's card form: `auto`,
`markdown`, `lavish`) decides the plan's form; `auto` lets the house choose, a surface for a
design choice and a page otherwise. Harbor's `light` and `full` were the old names for
`markdown` and `lavish`.

### What Approve carries

An approve takes an optional `--said`: what the user wants to say WITH the tap, the user's answers to the
plan's open questions above all. It is recorded as one note on the card by the human actor,
written by the same `kb approve` call that moves it, and at the PLAN gate the resume prompt
then quotes it and tells the house to apply the user's answers where they change the work and to
say in `context.md` what changed. On a lavish plan it composes with the annotation poll: the
prompt says to read the annotations and the user's answers together, as one answer. This is the
only way words of the user's reach a house whose plan is a markdown page; before it, answering a
plan's questions cost a send back and then a second approve.

At the OUTCOME gate the tap publishes, and ends the house of a card that is now done (a work
card at shipping keeps it, c-600), so there is nothing to resume:
`--said` is recorded and that is all ("merged, but follow up on X" belongs on the record).
The terminal's `kb approve --said` is the same note and never a resume, since kb runs no
houses; its help says so.

**An unanswered open question takes the plan's recommendation.** Every approve prompt says
it in one sentence, with or without `--said`, and the house contract
(`etc/house-contract.md`) is the other half: every open question a house leaves the user carries
its recommended answer, so a plain Approve means go with those recommendations and a house
does not stop to ask again.

Send back is the other answer: `sendback` notes the reason and resumes the house with it.
At the plan gate the card stays at `planning`; at the outcome gate it goes back to
`building`. Sending a plan back with `stay` opens a **discussion**: the card keeps its
gate open, `options.discussion` is set, and the house holds its slot (it was resumed, and its row is busy) in a poll and reply
loop until the surface goes quiet. That is the one time a house deliberately waits on a
human. See [houses](20-houses.md).

### What Approve outcome publishes

A work card's outcome is published by the adapter (the pull request to ready, the story
onward; the merge is a colleague's). A personal repo card has no adapter and its outcome is
a branch in one of the human's own repos, so the tap IS the merge (`keel/merging.py`).

**Which branch lands** (`merging.branch_placed`). A house's card lands the branch its
worktree has checked out, while that worktree is there (`merging.branch_of`): it is the one
fact that cannot be misspelt, and `kb stage review --output` takes whatever the house wrote
(a branch, `<branch> @ <sha>`, an artifact path). Only with no worktree is the branch read
from `output_ref` (`merging.named_branch`). A card Bosun builds (`derived.bosun`, read by
`merging.bosun_card` off the board's own card) never asks its worktree (c-647): Bosun builds
in its clone or a worktree of its own and records the branch as the outcome, so
`merging.bosun_branch` takes the word `output_ref` names (`<branch>`, `<branch> @ <sha>`,
`branch <branch> @ <sha>`) and only when it is a branch where it is read from:
`refs/heads/<name>` of Bosun's clone when the card's repo has one, else of the live repo.
A bare sha, a path, a sentence, the target or the trunk (compared casefolded: on a
case-insensitive volume `Main` resolves to `refs/heads/main`) or a revision spelt off a branch
(`main~0`, `x^0`, `x@{0}`: `merging.plain_branch`) is refused with one line saying
what to do (`merging.NO_BRANCH`: `kb stage <id> review --output <branch>`); there is no
fall back to the worktree. Before, a worktree left by a house started by accident named
the branch, and the approve fetched from Bosun's clone a branch that was never there. A
branch such a house left in the repo is not deleted: the landing names it in a note
(`merging.leftover_branch`).

**A proposal card's outcome is its draft, adopted** (c-667). A card that proposes a tier or
a flow (`options.tier_proposal`, `options.flow_proposal`) publishes nothing and merges
nothing: its outcome button reads Adopt, and that tap, from the deck or with `kb approve`,
calls `onboarding.adopt_proposal`, the function the Adopt button in Setup calls, which
writes the draft and then closes the card. A draft it refuses refuses the tap, and the
card stays at review with that reason. It closes no other way: a stage move to done, a
`land` relay and the drain's tracking close are each refused for it, and archive is how
one is dropped ([onboarding](89-onboarding.md), "Approve outcome on the card is Adopt";
[flows](64-flows.md), "Propose and adopt").

**A branch the in-app builder built is fetched at the user's Approve outcome** (c-619): by
the tap's own question whether there is anything to land (`landing.route`'s `tap`,
`merging.publish`, c-773), by the sha it pins and by the landing. Its branch lives in
Bosun's own clone (`<install>/builder/<repo>`), never in the repo it lands in. So for a card on a repo the in-app builder builds, `branch_placed`
first fetches the branch from that clone (`merging.fetch_built`, `merging.built_clone`: never
for a card the user gave a house, `options.worker`, whose branch is in its worktree of the live
repo and which is read, pre-run and landed like any house's, c-647), as the
landing's own user, into `refs/builder/<branch>` (never a `refs/heads`
ref of the live repo), only from a real clone under `<install>/builder`, refusing the trunk's
and the target's names; the merge takes that ref and is then the usual one ([Bosun](96-bosun.md), "The builder").
In bypass Bosun's own Approve outcome fetches it the same way, before its checks read the
branch (`authority.outcome_facts`); in auto mode nothing reads it before the user's tap.

**The deck never offers an Approve that cannot publish** (c-551). The adapter's `act links`
may carry `unpublished`, one line saying why the user's Approve could not publish a card at the
gate, read from the card's fields alone (no clone and no credential is touched).
`deckstate.card_view` lifts it to the card's `unpublished`, and the gate draws that line in
place of Approve outcome, with Send back as the act, on the card, on a kanban drop and on the
outcome page. The stage check above keeps new cards from getting there; this catches one that
reached the gate before it.

**A work outcome publishes here** (lane L). The code host's credentials and the worktree
are on this machine, so `kb approve <id> outcome` takes the approve lock, runs the space's
adapter `publish` (`adapters.publisher`) outside the transaction, and moves the card to done
(or shipping) only once it has answered; what it published is stored on the approve event.
A publish that fails leaves the card at review with the adapter's line. A Send back that
lands while the publish runs refuses the move, and the card gets a note that the pull
request may be ready while it is back at building. After the move, what the user said is noted,
and a card that is now DONE has its house ended in the tap (`house.retire_finished`). A work
card at shipping gets no such end: its house lives on (c-600). The deck's tap and the
terminal's `kb approve` are the same path.

At shipping the adapter publishes only inside a one-shot marker, `options.publishing`
(`Board.mark_publishing`, written by the user's Ship): the SHA-256 of a random nonce and the time,
never the nonce itself, so no read of the card (`kb show`, the deck) can show it. Nothing
else writes that option: `kb set` refuses it for every actor, and create, split and a row
insert refuse it (and `options.landing`, `options.rotate` and `options.cut_from`) outright. `kb ship` clears the
marker whatever happens, and any stage move drops it, so it never outlives the Ship.
Approve outcome in a space whose publish is a pack's marks the card the same way (c-738 r1.F3,
`cli.publishing_tap`, with `adapters.publishes_through_pack`), and both taps hand the verb the
nonce itself (`KEEL_PUBLISH_NONCE`, `adapters.publisher(..., nonce=)`; never inherited from
Keel's own environment). A pack on the kit runs `publish` only when that nonce's digest is the
marker's (`pulls.in_tap`), at every stage, so a house that runs it is refused even while the
user's tap is open.

**Review at shipping: verdicts and the user's Ship** (lane SHIP, c-600). There is no review round
and no second gate: the card stays at `shipping`, and the watcher tells its own living house
each batch of review ([the drain](30-drain.md), "Shipping"). The house records ONE verdict
per item it was told with `kb verdict <id> <handle> --verdict valid|not-valid|deferred|prepared --why
... [--summary ...] [--severity ...] [--commit <sha>]... [--reply-file <file>]`
(`Board.verdict`, `keel/shipreplies.py`): its own card only, at shipping, a handle it was
told. A valid item needs a code change (and only a valid one may carry one); a not-valid or
deferred one needs a reply; valid but not changed in this pull request is deferred, with its
reason (the method's rule, c-600 review). A fix that needs the user's yes before it lands
(r-55, c-723: c-240's branch rebuilt on a new base, which replaces published commits) is
`--verdict prepared`: the house prepares it without moving its branch, its why is what it
prepared and the question, it carries no reply (nothing is posted for it) and may name the
prepared commits (`shipreplies.prepared_verdict`). The card is then in needs you with that
question (`derived.ship_prepared`, `[{handle, why, at}]`, `shipreplies.waiting_on`, which
reads only the verdicts' handles, kinds, whys and times, never their diffs; `gate_since` is
its time) until the user answers it with a Send back, which is told to the house as its
next item like any other, or until a newer verdict on the item replaces it. A send-back
answers only the items it names, recorded before it: a line of its words led by the item's
handle and a colon (`c11: yes, move it`, as the deck's Answer leads them), kept as
`answers` on its note (`shipsendback.answers`, `Board.send_back`; c-723 review r1.F5), so
one answer never clears a second question. The handle is matched in any case, and a
second Answer tapped before sending adds its own `<handle>: ` line to the draft, so one
send-back answers both (r2.F6). The user's own send-back item is never
prepared (`check` refuses it: it is the user asking); the rebase item may be, since c-240's
was a rebuild on a new base that replaced pushed commits (r1.F6). The deck says "waits on you" with the
question, and its Answer opens Send back with the item's handle leading the user's words. A
`valid` with a note would have read as done, and the question lived only in the house's
end-of-turn text; a verdict kind is the smallest place for it, because the verdict is
already the item's one record and Send back is already the way the user's words reach a
shipping house (an ask is Bosun's, answered to Bosun, so it could not reach the house). `kb` reads the reply file
and each commit's diff (`git show`, cut at 12,000 characters) in the house's own clone,
where the worktrees are. A
`verdict` event is the record; a newer one for the same handle replaces it. The rows the
deck draws are derived: each told item (`options.shipping.told`) with its newest verdict and
the user's mark (`kb mark` with `doc: shipping`, `block: replies`, the handle as the row, post, edit
with the user's words, or drop). A row the user never marked posts its reply when it has one. Only what
was recorded SINCE the item was told counts (`shipreplies.since`, compared as instants, not
text): a handle told again (a check that failed again, a reviewer who asked for changes
again, a comment edited on the host) starts its row afresh, never with the old verdict or
the user's old mark (c-600 review). A reply once posted is posted: the user's edit or post on that row is
refused (`shipreplies.refuse_after_post`), since a second reply is never sent.

`kb ship <id> [--anyway]` (the user's alone; the deck's Ship) runs the adapter's `publish --answer`
with `{"ship": true, "replies": [...], "lease": {repo: sha}}`, only the kept replies not
posted yet. FIRST, against the worktrees as they are NOW
(`keel/shipcheck.py`, c-600 review), never the drain's last read: a Ship from a worktree
that has DIVERGED from its pull request's branch (ahead of it and behind it: the branch was
rewritten outside Keel, c-653) is refused with the record's own sentence
(`options.shipping.local.said`: the counts and the by-hand way) and, on the same line, the
commands that bring the worktree in line (below), and
`--anyway` does not override it, since that push cannot succeed and the push goes before
any reply. A worktree only BEHIND that branch (a colleague pushed to it) is not refused: it
has nothing to push, the adapter skips a push of a branch the remote already holds
([the work adapter](60-work-adapter.md)), and a kept reply or a draft still goes. A Ship with nothing to
ship (no commit the pull request lacks, no draft, no kept reply) is refused; one while the
house is in a turn, or with commits no review receipt covers, is HELD with the reason
(`Ship held: ...`), and runs only when the user says so (the deck asks "Ship anyway?", the terminal
passes `--anyway`). Then the adapter looks at each worktree's branch ON THE REMOTE, asked at
that moment, and pushes only a pure fast-forward, PLAIN, with no force flag,
so a push by anyone else in between is rejected by the remote and never overwritten; a worktree the remote
is ahead of is skipped, and one that has diverged refuses the whole Ship before anything
is pushed ([the work adapter](60-work-adapter.md)). The head Keel last recorded
(`options.shipping.heads`: what the user's Approve published, then what each Ship pushed) is the
lease of a push only when the remote could not be asked: it goes stale the moment the branch is
rewritten outside Keel, and a Ship after the user has brought the worktree in line by hand must
not be refused on it. It marks a draft pull request ready, and posts each
reply threaded under the comment it answers, deduplicated against what the author already
said. Its answer's `sent` is kept as `options.shipping.posted` (per handle, `Board.ship`) and
its `pushed` as the next lease, with a `ship` event. The event's line
(`shipreplies.ship_line`, the deck's toast after Ship) names only a repo whose head moved:
the adapter answers `pushed` for every worktree, so a Ship that moved none said "pushed web
01282a6" after its confirm had said "nothing new" (c-605); a head equal to the one recorded
before says `nothing new to push`. That write also stops saying the send still waits, with
no git at all: `local.ahead` and `local.unchecked` are dropped from the record
(`Board.SHIP_SENDS`), and what is known of a branch behind (`behind`, `diverged`, `said`,
`by_hand`, `conflicts`) stays. Were `local` the drain's alone (c-660), for up to a
couple of minutes after a Ship the record would still say the commits just pushed were waiting,
the deck would draw the push again, and a second tap would be refused with nothing to send
(c-037).

**After the record, the worktrees are read again** (`shipping.after_ship`, called by `kb
ship` once `Board.ship` has returned, c-660). Nothing stands between the adapter's answer
and the write that records it: a slow read there could have lost `posted`, `heads` and
`shipped_at`, and the next Ship would have posted the same replies twice. The read is the
drain's own `local_facts`, made STRICT (a git call that gave no answer is `shipping.Unread`,
never a zero) and under ONE deadline over the whole of it (`AFTER_SHIP_SECONDS`, 5, on a
thread nothing waits for past it). Read, its facts are laid over the record as `local` in a
second short write (`Board.keep_shipping`, as the user). It is a READ, not a sum from the
adapter's answer: `ahead` is one count over every worktree, the answer names heads, not
counts, and a commit the house made while the push ran still waits. UNREAD (git did not
answer, the read failed, the deadline passed) writes nothing: the Ship is neither failed,
delayed nor repeated, the record keeps what the first write left (no send offered, the
branch's kind as it was known), and the drain's next pass reads the rest without saying
its sentence again. A worktree this read finds newly behind or diverged is said on the card
as the user's Ship's own finding: a note of the user's, in the one sentence (`shipping.say_local`),
which no drain pass repeats: the sentence is said once per change of kind whoever finds it,
skipped only when the card's newest out-of-step note (a note whose data carries `local`,
the kind) says that same sentence and was written within the last minute
(`SAID_LATELY_SECONDS`), so a pass that read the record between the Ship's two writes adds
none, and a branch behind again an hour later is said again. A base this clone never
fetched is no conflict known to either read (`shipping.conflicts` asks `rev-parse --verify`
for `origin/<base>` first and never reads it off merge-tree's exit, which is 1 or 128 by
git's version: such a card once read as conflicting), and never unread: only a git call
that did not run is. The card stays at shipping. `kb ship`
writes the user's tap's `options.publishing` marker for the adapter's run (`Board.mark_publishing`
with `ship`, then `Board.ship`): at shipping the adapter publishes only inside it. A declined
pull request refuses it. Nothing the house does posts or pushes: at shipping its push, the
adapter's `pr` and `publish` are refused (the adapter, its settings and the house guard,
[drain](30-drain.md), "Shipping"). The user's Approve at review on a card still in an old review
round (from before c-600) is refused until `bin/keel-shipping-upgrade` carries it.

**A pull request's branch rewritten OUTSIDE Keel** (c-653, `keel/shipstep.py`). It happens
when the remote branch is force-pushed (its commits replayed onto another
base) while the card's worktree keeps the old history: a house commits on top of it, and
its fence refuses the rebase it needs, so nothing can leave that worktree again. **Keel
moves no branch for the user here.** A tap that rewrites the branch is not offered:
each review of one found a new way it could lose work (c-659 is
the card for that tool). The first-run design (c-668) asks for that tap again, "Bring the
working copy in line"; c-678 left it out for this reason, and said so.
What Keel does is say what is so, and give the user the exact commands,
worked out READ-ONLY (`rev-parse`, `rev-list`, `reflog`, `merge-base`; never a fetch, a
ref, the index or the worktree).

Only the worktrees a pull request of the card is on are looked at (`shipping.ship_trees`:
each keyed by its own repo, and one whose repo has no pull request is left out), each
against `origin/<its branch>` as last fetched and never its upstream (`origin` here and in
the commands below is the space's `remote` setting, `origin` unless it says, c-665:
`config.remote_of`). For each that is
behind (`shipstep.by_hand`, kept on the card as `options.shipping.local.by_hand` beside the
one sentence, `local.said`):

Each worktree gets ONE command, a chain joined with `&&` (`shipstep.chain`), so a paste
into a terminal stops at the first step that fails and nothing after it runs somewhere
else. Every chain starts the same way: `cd <the worktree>` (quoted for the shell, as the
branch is); a guard that HEAD is still the commit the chain was worked out for (`test
"$(git rev-parse HEAD)" = <sha>`), so a block read before the house's next commit does
nothing at all, and the sentence says so (if it does nothing, the card has a newer one);
and the fetch of that one branch by its full refspec (`git fetch origin
+refs/heads/<branch>:refs/remotes/origin/<branch>`, as the adapters fetch it: a clone with
a narrowed refspec would otherwise be replayed onto a stale ref). Then:

- **Only behind** (a colleague pushed to the branch): `git merge --ff-only
  origin/<branch>`, which cannot lose a commit and refuses to overwrite an untracked file.
  Nothing is refused meanwhile: Ship still sends what needs no push.
- **Diverged, and Keel can tell which commits are the card's own**: those after the last
  position of this history the remote held (`shipstep.old_head`: of the head Keel last
  recorded as pushed, `options.shipping.heads`, and the newest of the remote-tracking
  branch's last 50 reflog positions that is an ancestor of HEAD, the nearer winning). A
  backup branch of where it stands (`git branch -f keel/backup/<card>-<short sha> <head>`,
  named for that commit, so typing it twice is harmless), and only when that succeeded
  the replay of exactly those commits (`git rebase --onto origin/<branch> <the old
  head>`); or, with no commit of its own, the move of the branch by `git checkout -B
  <branch> origin/<branch>`, which refuses to overwrite an untracked file (never
  `reset --hard`).
- **Diverged, and rebuilt HERE** (r-55, c-723, the c-240 case: the house replayed the
  branch onto a moved base with the user's yes, and the remote is still at the head Keel
  last recorded as pushed, `shipstep.published`): nothing outside Keel rewrote anything,
  so the sentence says the branch was rebuilt here (`REBUILT_NOTE`), never that it was
  rewritten outside, and the house's batch says the same (`shipround.REBUILT`). The entry
  carries `rebuilt` and the command publishes it (`shipstep.republish`): a backup branch
  of the published head (`keel/backup/<card>-<short sha of that head>`), then `git push
  --force-with-lease=refs/heads/<branch>:<that head> origin HEAD:refs/heads/<branch>`,
  leased on the exact head, so git refuses it if anyone pushed since and nothing is
  overwritten. The sentence names what the push replaces before it is pasted: the count
  and short shas of the published commits HEAD does not hold (`replaces` on the entry,
  `shipstep.replaced_line`, c-723 review r1.F7), since the rule that calls it a rebuild
  reads only that the remote is where Keel left it, not how the worktree got here. Ship still refuses the diverged worktree (it only fast-forwards), with
  that sentence and that command; the push is the user's own paste.
- **When it is not known** (no recorded head and no recent earlier position of the
  remote-tracking branch is in this history), **or the card's own commits include a
  merge** (c-651's rebase item has the house merge its base in, and a replay would flatten
  the merge and lose its resolution), **or git could not be read** (a count that could not
  be read is never taken for zero): no command. The sentence says why, and that it needs a
  hand.

A third kind is said the same way (c-718): a STACKED card whose parent was squash-merged
into the base still carries the parent's old commits, though nothing rewrote its own
branch. Its entry replays only the card's own commits onto the base and pushes with a lease,
by hand ([the drain](30-drain.md), "Stacked cards").

An entry is worked out once: it carries what it was worked out from (`at`: HEAD, the
remote-tracking sha, the recorded head), and while those three are unchanged the stored
entry is kept (`shipstep.one`), since this runs on every drain pass and again in the user's
Ship's check. It also carries `v`, the way it was worked out (`shipstep.WORKED_OUT`, 2
since c-723): an entry of an older way is worked out again once, so a card already in the
c-240 state when the rebuilt-here case shipped gets its sentence and command, not the
replay kept from before (c-723 review r2.F7). An entry whose git read FAILED (a timeout, an OSError, on the reflog, an
ancestor check or a count) says git could not be read and is never kept: the next pass
tries again. Only a walk that ran and found no earlier position says Keel cannot tell.

The sentence and the command are shown in three places and are the same text everywhere:
the card's note each time the kind changes (the sentence), the deck's line with the chain
in a block the user can copy ([the deck](40-deck.md), "A shipping card on the deck"), and `kb
ship <id>`'s refusal, which carries it on its one line. The user runs it while the house is in no
turn; a conflict in the replay is the user's to resolve in that terminal, with the backup branch
to return to. After it the worktree is ahead of the remote's branch and nothing else, so
Ship is offered again, and its push is a plain fast-forward of the remote's head as
fetched then, whatever head Keel had recorded (above). The replayed commits are new ones,
so no review receipt covers them and the usual Ship hold says so until the house runs
`keel check`.

While the branch is out of step, **no merge of the base is asked of the house**
(`shipreoffer.refusal`: `Board.reoffer` refuses `--rebase`, c-655's Bring the branch up to
its base, and a plain ask whose only offer would have been that merge, with the sentence
saying to bring the worktree in line first; the deck does not draw that button; and the
drain's fill adds no base-merge item of its own on such a branch,
`shipreoffer.behind_or_conflicts`):
a merge on top of that history is one more thing to untangle. A base-merge item asked
BEFORE the branch went out of step is told to the house as held (`shipround.REBASE_HELD`:
record it deferred), so a prompt never says both "merge the base in" and "never merge".
The review itself can still be handed over: the hand-over's confirm says the branch is out
of step and that the house is told so.

**What goes to the house by itself is the user's choice, per kind, and off unless the user says**
(c-655, `keel/shipauto.py`): `ship_auto_comments` (comments and reviews asking for changes)
and `ship_auto_checks` (failing checks), each a setting of the space with the card's own
option of the same name over it (`kb set <id> options.ship_auto_checks=true`; `null` for
the space's again; the user's alone, a bool or nothing). With a kind off, the watcher keeps its
new items on the card as `options.shipping.untold`, told to nobody, until the user hands them
over or turns the kind on ([the drain](30-drain.md), "Automatic handling"). The card
carries both for every reader: `derived.ship_auto` (`{comments, checks}`, each `{on, by}`
with `by` the card or the space) and `derived.ship_handover` (`shipauto.handover`: how many
comments and checks the user's hand-over would give the house now, whether the branch is behind
or conflicting, whether a hand-over is already asked, and the batch the house is still on).
It is derived for every shipping card on every read, so it reads little (`views.ship_handover`):
the turn's events only after the mark of the batch told last, a verdict as its handle and
time, never its diffs. A check counts only while the last look saw it failing, nothing
already waiting in the batch or posted counts, and a declined card has none at all.

**Send back at shipping** (c-663, `keel/shipsendback.py`). A card at shipping only goes on
to done, and until c-663 the one way to have something changed there was to open the
house's session and type. `kb ship <id> sendback --words "..."` (or `--words-file <file>`,
`-` for stdin) is the user's own notes for the house, theirs alone (`shipsendback.ACTORS`, the user's
token), and the deck's Send back on a shipping card is that verb run as the user. THE CARD
STAYS AT SHIPPING: no stage moves and no second gate opens. `Board.send_back` keeps the
ask as one more entry of `options.sendback`, a record of Keel's own beside
`options.shipping` and never inside it, with the handle its item will have (`his-<n>`) and
a note carrying the user's words; `kb set` refuses the option to every actor, a card is never
filed with one, and only the drain's take removes an entry, by its handle
(`Board.take_sendback`), so its write of the watcher's record can never drop one
(c-653's seam, `Board.keep_shipping`, is for `options.shipping` alone). It is refused off
shipping, on a blocked or archived card (the drain does not tend one), on a card whose
pull request was declined, and with no words. A move off shipping drops what still waits
(`Board._move`) and says so: a note names each send-back the house was never told, the
asks still on the card and the user's items still waiting in the batch (`SENDBACK_DROPPED`, the
handles in the note's `sendback_dropped`; the user's words are in the note that asked). A block
or an archive keeps it, unlike a re-offer, because these are the user's words: they are told once
the drain tends the card again.

Each send-back is one item of its own kind (`his`) in the card's batch, and several before
the house is told are several items, never one appended text: each has its own verdict and
its own row, and a later one never takes an earlier, judged row back to unjudged. The
house judges it like any item (`shipreplies.his_verdict`): `valid` with the commits that
did it, or `not-valid` or `deferred` with the why saying plainly why not; a reply is
optional and is its answer to THE USER. Nothing is ever posted for the item
(`shipwatch.UNPOSTED_KINDS`, with the rebase item): its row is marked `his` and carries no
words for Ship, the user's post or edit on it is refused (`shipreplies.refuse_after_post`), it is
never among the replies Ship posts and never counted in "replies to post"
(`shipreplies.postable`, `summary`), and it is not an item the user's Ship has yet to answer
(`shipwatch.open_told`). The commits it leads to go out with the user's next Ship like any
others. What the user sent and the house has not been told yet is `derived.ship_sendback`
(`shipsendback.waiting`: `[{handle, text, at, held}]`, `held` the sentence saying why the
drain is not telling it now, `shipsendback.held`: the pull request declined, the card
archived or blocked, the house stopped by the user (it goes with their Resume), the drain paused,
or its house still on a batch the user re-offered (the ask is taken once that turn ends or that
house is no longer running, [the drain](30-drain.md), "The user's own send-back");
None when it is told once its house is free, waiting like any item while the house is in
a turn). How the drain tells it is in [the drain](30-drain.md), "The user's own
send-back": as an ordinary item of the batch, on no hand-over mark, so a turn that leaves
it unjudged leaves it as any unjudged told item (the pane's "judging N", its row saying
"told, not judged yet", the user's hand-over able to offer it again) and neither blocks the card
nor stops its house.

`kb ship <id> reoffer [--rebase]` (c-651) pushes and posts nothing: it is the user's ask alone
(`shipreoffer.REOFFER_ACTORS`, the user's token) that the drain tell the house the review the
watcher's baseline hid, and every item it was told that has no verdict since (c-654: told
is not judged, so an unjudged item is offered again and a judged one never is; and with
`--rebase`, bring its branch up to its base by merging the
base in), written by `Board.reoffer` as `options.reoffer`, a record of Keel's own like
`options.shipping`: `kb set` refuses it to every actor but the drain, which clears it once
it has answered, and no card is filed with one. A house and Bosun are refused. So is a card
that is blocked or archived (the drain does not tend one, so the ask would wait unseen), and
`kb ship <id> --rebase` without `reoffer` or `kb ship <id> reoffer --anyway`. Any move off
shipping clears the ask (`Board._move`), and so do the sync's fresh record
(`Board.ship_from_sync`) and a block or an archive, with a note (`Board._drop_reoffer`). The `rebase` item it may bring answers no reviewer: its verdict is
`valid` with the merge commit or `deferred` with a why, never with a reply
(`shipreplies.rebase_verdict`), the user's post or edit on its row is refused
(`shipreplies.refuse_after_post`), and Ship never posts it (`shipreplies.postable`). What
the drain does with the ask, and the house stopped once its turn on that batch ends, are
in [the drain](30-drain.md), "A re-offer". A turn that ends with items of that batch
unjudged blocks the card for the user with them named (c-654); unblocked, this verb offers them
again. While the house is still on a batch (its own turn on it has not ended), that
batch's items are not offered again, and an ask with nothing else to offer is refused
saying so.

**Approve on a review card** (lane RC). A review card's outcome is the review kind (its
orientation, one `finding` block per finding with its post, edit or drop, the verdict decision; [plans on
the deck](47-plans.md)), and the user's Approve POSTS it on the colleague's pull request. It is the
same tap and the same path;
`adapters.publish` hands the adapter an ANSWER (`keel/reviewround.py`): each row at post
with the house's drafted comment, each row at edit with THE USER'S words, both at the row's
`path:line`; one summary (the outcome's paragraph saying what the change does, and the
counts); the verdict the user picked (comment only posts none, request changes and approve post
that answer); and the ledger of every row. An edit left empty, a verdict in the user's own words or
a row with no words refuses the Approve before anything is posted. The adapter posts the
comments, then the summary, then the verdict, recording each on the card as it lands
(`options.review_posting`), so a retried Approve never posts anything twice; the card goes
to `done` with `options.review_posted` (the head reviewed, the ids, the verdict, the
ledger). Nothing posts on its own, not even for an autonomous card: only this tap runs
`publish`.

**Re-review** (lane RC, RC-5). After the user's review is posted, the fetcher keeps an eye on the
pull request: new commits put `options.review_new` on the done card and one note, "new
commits since your review", and the deck draws Re-review (the Continue group). `kb
rereview <id>` (the user's alone, `Board.rereview`) is a new ROUND on the SAME card: the round
counted (`options.review_round`), `review_new` taken, back to `assigned` (its claim
dropped), so the drain starts a FRESH session in the review pool. That session is rotated
by construction: the adapter keeps the last round's record as `context-round-<n>.md`, moves
the worktree to the new head, and the brief hands it the change since the head the user reviewed
(`review-since.diff`) and what the user posted and dropped (`review-ledger.md`, from
`options.review_posted`); `kb stage review` refuses a finding raised again where one the user
answered sits, on lines that did not change (C31).

**The tree that is tested is the tree that lands** (E5 of the overnight clearance, c-298).
The merge commit (naming the card) is built in a temporary worktree,
`state/worktrees/<id>.landing`, detached at the target branch's head; the repo's test
command (`[tests]`, else the "Run the tests" line of its adopted CLAUDE.md, c-678,
`repocommands.tests_of`) runs on THAT tree, after the repo's prepare command where its file
names one (`merging.prepare_merged`: a tree that cannot be prepared lands nothing); and the live checkout takes it with `git merge --ff-only`, which
is the compare-and-swap. A target that moved while the suite ran refuses the fast-forward,
and the merge is built and tested again on the new head, once; a second move is a refusal
("moved twice"). The card's own branch and worktree are never touched by the trial, and the
temporary worktree is removed on every path. A branch this machine does not have (c-306) is
refused by name rather than reported as a conflict. Then the worktree and branch are removed, and
the merge sha is recorded on the approve event.

**The landing is local, and says so** (c-665). A landing pushes nothing, so what the
approve records ends "merged into `<target>` locally, not pushed", the receipt says "not
pushed", and Keel's two landing flows say it in their drawing ([flows](64-flows.md)).
Pushing after a landing is not built: who may trigger a push (Bosun's own approvals land
too), for which repos of a space, and whether inside the tap's budget or after it, is the
owner's decision, not a default.

**The tap's budget** (lane E round 4, finding 4). Keel's own suite takes about seven
minutes and the deck waits three for its `kb approve`, so the deck hands kb its budget
(`KEEL_TAP_SECONDS`, the wait less 30 s) and the merged-tree suite gets no longer. It runs in a
process group of its own, is killed whole when the budget runs out, the `.landing` tree is
removed, nothing is merged and nothing is blocked, and the card gets one note: the suite ran
longer than the deck waits, land it with `kb approve <id> outcome` in a terminal (no time
limit there) or with the merge queue on. A second approve while a suite for the same card is
still running is refused with that same advice (`merging.approve_lock`) rather than starting
another.

**Where it lands, and when: the landing queue** (`keel/landing.py`, E5). It shipped
DORMANT (lane E review round 3) and is ON in the shipped example, and on the owner's install since 2026-09-24. With `[keel]
merge_queue = false`,
every Approve outcome lands inside the tap, as above, no drain carries or announces a
`land` relay, and `kb land` refuses outright. With the flag on, a personal repo card goes
through the drain as a `land` relay (`kb relay <id> land --to <host>`, the human's, only at
review, one pending per card): the card lands through this machine's drain, so the tap returns at once rather
than holding the deck's 180 second request for a whole suite.

**The relay pins what the user approved** (lane E review finding 1): `--sha` is the branch's
sha at the tap, and that sha, never the branch by name, is what is merged on every attempt.
**A drain only carries the kinds it knows** (finding 3): it writes its pid and the kinds it
carries (`land` only with `merge_queue` on, `rotate` only with `rotate` on) to
`state/drain.json` when it starts (`drain.announce`). A drain that meets a kind it does not
carry leaves it pending with one log line; it never reads it as a stop.

The drain that owns the card takes the relay and spawns `python3 -m keel.landing <id>
--relay <n>` in a session of its own (a suite cannot run inside a pass), logging to
`logs/landing.log`. The worker writes its pid on the card BEFORE it waits on the repo's lock,
so a queued worker is never taken for dead, and a card whose own landing or pre-run is
running starts no second one. Under the lock it reads the card again and lands only if the
card is still at review, unblocked, not moved since the tap, and its branch still at the
pinned sha. It ends the card's finished house first (as the tap does after), and lands
nothing if that house is working. Working is the one rule every reader asks
(`housejobs.working`, c-535 and r-26, [houses](20-houses.md)): a listed process whose `state`
is `working`, never its `status`: an idle house whose background job still runs is listed
`status: busy`, `state: done`, and c-532's sat 46 minutes on a polling loop and blocked its
landing. Such a house is stopped like any finished one, and the stop ends its jobs
(`housejobs.stop`); a row with no `state` falls back to `status`. A row listed as working
with no process behind it (r-26, c-561's 735f0cab) is stopped too and landed past with a note
naming it. The refusal for a working house opens with what the user can do (Stop session on the
card, then Approve again) and names the row: bg id, session, state, status and pid. Right before the fast-forward AND right before the cleanup
it asks again (`landing.guard_for`): the card still at review, unblocked, its landing not
cancelled (`Board.stage` marks a testing landing `cancelled` when the card leaves review, so a
Send back mid-suite is honoured), no stage move since the tap, and the house not live. A
reason before the fast-forward lands nothing; one after it keeps the worktree and branch. A
refusal is clean (marked `refused` for that relay, the card blocked only while it still waits
at review). A merge that landed is never reported as not merged: if `kb land` then refuses,
the card is blocked with "merged into <target> at <sha>, but not moved to done because <why>", and
a failed cleanup after it is a note. The cleanup deletes the card's branch only once it is
an ancestor of the target (`git merge-base --is-ancestor`), and then with `git branch -D`:
`-d` checks against the checkout's HEAD, main, and so refused every branch landed on `next`
(c-530, c-535); a branch that moved past the merge is kept and said. `options.landing` is written only by the drain
(`Board.set_fields` refuses anyone else), and `kb land` checks facts rather than it: the sha
the relay pinned must equal the worker's record AND be in the repo's target branch per git
here (`merging.target_has`). A same-user shell can still reach the board, but
"done with nothing merged" needs git to agree. Anything unexpected is an answer on the card,
never a traceback. The worker holds the repo's lock (`state/locks/land-<the repo's path>.lock`),
so one landing, pre-run or deploy per checkout runs at a time (the lock is named by the
repo's path, since Keel is a repo of two spaces) and the rest wait in relay order; it runs
the same `merging.publish`, and answers on the card: `kb land` to done (the house is then
retired, as the tap does), or blocked "outcome not merged: <why>" (marked `landing-refused`:
the house staging review again clears that block in the same write, since a new outcome is a
new approve, and no other block, r-26; `board._clear_stale_block` does it, and lifts the
Stop hook's own "stopped at building after N nudges" block, marked `stop-check`, on any move
off building, since it rode a house's own move to review into shipping, c-601), or on a conflict the
house is resumed to merge main exactly as the tap would. `options.landing` is what the deck
shows while it runs (`testing`, with the worker's pid, then `landed` or `refused`); the
pending relay is "land asked of <host>". A worker that died is answered by the next pass
("ended without an answer"). With the flag on, the drain also pre-runs the merged tree of
one card at review per pass (R5) and records `options.pretest` (`green`, `red` or
`conflict`, and the two heads it was built from), once per pair of heads. A move to review
drops a finished pre-run's record (`Board._drop_pretest`, c-621): it answered for the outcome
staged before, and the deck showed it beside the new one; a running one is kept, keyed on
its heads. The tap's note says the merged tree lands untested when the repo has no test
command, and why (`actions.landing_note`, `repocommands.untested`: no `[tests]` entry, and
for a repo the install copied, no Run the tests line in its CLAUDE.md); the card's outcome
gate says the same before the tap, under "lands untested" (the state's
`spaces.<name>.untested`, c-678). A repo whose CLAUDE.md changed since the user adopted or
saved it, in a space with no pack whose config names no test command for the repo, is
refused before any tree is built (`repocommands.landing`, `merging.FileChanged`; a pre-run
records "not run" for it, never red), and
the note and the gate say that instead ([onboarding](89-onboarding.md)). A red suite's
refusal names what failed on its first line, which is what the block, the note and the
CLI's one line carry: every `FAIL:` and `ERROR:` test by its dotted id and every failed job
(`voice: exited 1`), ten at most and a count of the rest, and the path of the whole output,
which every merged-tree run (the tap's, a landing's, a pre-run's) keeps in
`state/cards/<id>/merged-tests.log` (`merging.failures`, c-535; a 15 line tail had named no
test for c-534). The deploy worker names its failures with the same parser. A dirty checkout, a red suite
or a conflict refuses the whole thing: nothing is half merged, the card is blocked with the
reason (under needs you, Drop in ready), and approving again after the fix merges. Only a real conflict is a conflict (`merging.conflicted`: git said CONFLICT, or left
unmerged paths); a merge git refused another way (no committer identity, a hook) is
`merging.NOT_CONFLICT`, carrying git's own first lines, and blocks the card for the user: a
house that merges main cannot answer it (c-621, a clean user's house looped on "main
moved"). One
refusal is handled without the human: when the merge conflicts because the target branch
moved after the house branched, the deck's approve unblocks the card, stages it back to
`building` and resumes the house with the merge as its task (`git merge main` in its
worktree, resolve by intent, test, commit, stage `review` again); the card carries
`options.merging` meanwhile, which the deck shows as the house word "merging its target"
(the card does not record which branch moved, so the word names none, c-665), and the
turn-end hook clears it once the card is back at review. A card Bosun builds resumes no
house (c-647): it goes back to `building` with a note that it is waiting for Bosun to merge
the target into its branch, the receipt says the same (`landing.bosun_why`), and
`options.merging` is not set; nothing wakes Bosun for it ([Bosun](96-bosun.md), "The builder"). The next approve merges clean. The terminal's `kb approve` only blocks, since it does not run houses. On a house's card an outcome
that is not a branch (a URL, an artifact path) and no worktree publishes nothing. On a card
Bosun builds it is refused with the sentence above ("Which branch lands"), unless the card
has nothing to land by its kind: a `research` card closes as below whatever its outcome
names, since `merging.is_research` is asked before any branch is read. A worktree a house
left at such a card's path is still removed and its trust entry forgotten when it closes
(`merging.drop_leftover_tree`); no branch is deleted there. Only the no-branch refusal
(`merging.NoBranch`) does this: on any other refusal (a clone's branch, where the close
did not read it with the fetch) a card closed with nothing to land keeps the worktree at
its path. A card with nothing to
land (r-24, `merging.nothing_to_land`) closes as done in the tap with the note "nothing to
land: the outcome is its record" on the approve, and no relay, pre-run, merge or suite: a
card whose `options.kind` is `research` (its outcome is its findings), or one whose branch
has no commit its target lacks (`git merge-base --is-ancestor`). `merging.placed` answers
None for both, so the pre-run skips them and `landing.route` sends them to the tap. A card
Bosun builds is read from its clone only at the user's tap, so the tap asks with the fetch
(`landing.route`'s `tap`, `merging.publish`, c-773): one whose branch already landed under
another card (a stack reviewed and landed as one branch) closes in the tap the same way,
where it was once queued and then refused for having no branch to land. That close reads
the branch once and cleans up what the tap fetched: the `refs/builder/<branch>` ref is
deleted (`git update-ref -d`, `merging.drop_branch`) because the target already holds it,
even when it is another card's branch that landed with this card's work, and a worktree a
house left at the card's path goes with its trust entry. Bosun's clone keeps the branch,
no `refs/heads` branch of the live repo is deleted on this path, and a fetched ref the
target does not hold is never this close's to drop. A branch the tap cannot read (the
outcome names one the clone no longer has, or the clone is not a real one) is not
"nothing": the card takes the landing path, the approve is refused with the reason, and
it stays at review. A land
relay queued before its branch turned out empty closes the same way when the pinned sha is
already in the target. The close gives up the worktree as a landing does
(`merging.close_unlanded`): the worktree and its trust entry go, and the branch goes only
when its target already holds it; a research branch with commits of its own is kept, and the
note says so. Bosun's outcome approval of such a card is refused: closing it without a merge
is the user's tap. In both spaces
the tap also ends the card's house if the harness still lists it and the card is done (a
finished house has nothing left to do), noted on the card as "finished house <id> stopped";
a work card at shipping keeps its house (c-600).

### The integration branch: a Keel outcome lands on next

For a repo where merging is deploying (Keel: this machine runs `main`), `[integration]`
in the install's `config.toml` names the branch approved outcomes land on instead (`keel = "next"`, c-526).
`Config.integration_of(space, repo)` is the one source, and it is config, never a card field,
so no house can retarget its own landing; a space with an adapter never has one.

**A card's own base never overrides it** (c-732 r1.F4). In a space with no pack, a card may
name its own base (`options.base`, one of the space's bases, [flows](64-flows.md), "A space's
bases"), and is cut from and lands on it. Not on a repo with an integration branch: the board
refuses a base there at create, at set and on each slice of a split (`Board._refuse_base`),
and beneath that every reader ignores one that got past (`merging.card_base`, read by the
cut, the landing target, the trial, the house's base, the review diff `fixcheck.run`, the
stage check `stagecheck.base_check`, a resumed house's brief `prompts.afresh`, and a flow
move's `bases`, `flows.based`, wherever the config is at hand; c-732 r2.F1; the stage check
gets it from `plangate.contract_checks`, and `tests/test_bases.py` holds it there, c-733), so such a card
is cut, reviewed, stage-checked, briefed and landed by the integration rule below, the trunk merged in, `next` created at the trunk. This protection sits below
Bosun's own outcome check (`keel/authority.py`, which reads `cfg.integration_of`), so a card
Bosun files with a base cannot put work on the trunk under its approval. How work ships offers
no bases for such a space and names the integration branch instead.

- **Landing.** `merging.placed` targets the integration branch, so the tap, the landing
  queue, the pre-run, the conflict path (the house merges `next`, not main) and `kb land`'s
  fact check all follow it. Nothing has `next` checked out, so it moves by `git update-ref
  refs/heads/next <new> <old>`, the compare and swap (`merging.settle_integration`). It is created at main's
  head the first time anything lands. When main has commits `next` lacks (the user's own commits to
  main), the trial tree merges main in FIRST ("Merge main into next"), so the suite runs on
  what `next` becomes and a deploy is always a fast-forward; a conflict there is not the
  house's to fix and blocks the card for the user. The live checkout is never touched, so a dirty
  one does not stop a landing. The card goes to done: its work is on `next`, tested, not live.
- **Building.** Every card on the repo builds from `next` (the user's D1): a new card branch starts
  there (`adapters.start_point`; HEAD before
  anything has landed), and the house brief's review base, rebase line and the stage
  check's "contains the base" read it (`house.target_of`, `stagecheck.base_check`), so a
  card is reviewed against the branch it lands on. `options.base` wins only where the repo
  has no integration branch (a work card, a card on one of a space's bases), and a card stacked on a card that has not landed is taken against that card's branch
  before either ("Stacked or independent", below).
- **Waiting.** An `after` on a card of such a repo is met only when that card is DONE (the user's
  D2): at review nothing is on `next` yet (`views.waitable`, fed by `Board.integrated`).
  So a stack of dependent cards builds end to end on `next`, each on the last one's landed
  work, with nothing deployed; in builder mode Bosun approves each outcome of a personal
  card ([Bosun](96-bosun.md), "The outcome gate").
- **Going live** is its own step, the user's alone: the drain's deploy ask and the deploy worker
  ([the drain](30-drain.md), "Deploy").

## Derived, never stored

- **needs you**: a gate is open, or `blocked_reason` is set, or the card is an open
  segment notice, or Bosun has an open ask about it (`derived.ask`, c-521), or its shipping
  house prepared a fix that waits on the user's answer (`derived.ship_prepared`, r-55,
  c-723, "Review at shipping"); never for an
  archived or backlogged card, and never for an outcome gate that is landing. That is Q8's
  list and nothing more (N3: no general queue).
- **landing**: `derived.landing` (`views.landing_now`, c-535), the card at review and
  unblocked with its Approve outcome on record: a `land` relay pending, or the worker's
  `options.landing.state` at `testing`. It takes the outcome gate out of needs you (c-533
  sat 14 minutes there while its merged tree was tested); a refusal blocks the card, which
  needs the user again. `kb list` flags it `[landing]` and the deck's outcome word says
  `landing` (`landing · testing on <host>` while the suite runs).
- **held by the user's Stop**: `derived.held_by_stop` (`views.held_by_stop`, c-605 review): the
  card's newest marked Stop note (`human-stop`) is newer than its last turn start and the user's
  last Retry (`views.stop_holds`, the one rule the drain and a review batch read too). The
  deck's house word says "stopped by you: waiting for your Resume".
- **closed while idle**: `derived.closed_idle` (`views.closed_idle`, c-607): the newest
  marked note since the last turn start is the user's Close idle house (`closed-idle`), not their
  Stop (`views.stop_kind` reads both). The drain's resume of an exited house passes it over,
  its next review batch, the user's gate answer or Resume brings it back, and the deck's house
  word says "closed while idle: the next review or your tap resumes it (about 5 to 15 s)".
- **idle at shipping**: `derived.ship_idle` (`views.ship_idle`, a-72): for a shipping card,
  `{since, close_at, hours}`, when its current session's turn ended by its newest `Stop` hook
  (no turn since) and when the drain closes the house if the harness still lists it idle
  then (`keel/shipidle.py`); None with no Stop on record.
- **gate since**: `derived.gate_since`, when the wait on the user opened, from the event that
  opened it (F5): the newest `block` (or a `set` of `blocked_reason`) for a blocked card,
  the newest of the move to planning, the `plan_ref` and the switch to attended for a plan
  gate, the move to review for an outcome gate (the backlog rule's own stamp), and the
  filing for a notice, and the ask's own time for an open ask. `Board.opened_since` reads it; an import with no such event falls
  back to `updated_at`. None for a card that waits on nothing
- **notice**: `options.notice_key` is set and the card is not `done`. A segment files its
  notices this way (`bin/keel-backup`, cloud-spend's fetch: personal, attended, topic
  `notice`) and closes one by staging it done, from inbox (the board allows `done` from any
  stage for a notice and for nothing else). Before J-1 that close was refused outside
  review and every closer swallowed the refusal, so no notice ever retired itself (c-440
  sat open after three good pulls); a failed close is now said in the closer's log. The
  `notice` topic is only a grouping word,
  so it decides nothing; the key does. Before F6 of the overnight clearance a notice sat in
  the inbox among the user's ideas and never reached Attention.
- **kind**: a card with no `repo` is an errand (restricted tools, no worktree); with a
  repo it gets a worktree. `kb create` says so on stderr when it files a card with no repo
  and no `--new-project`, because an errand cannot change code whatever its title says
  (c-296). It is a line, not a
  refusal: an errand is a real kind of card. A `repo` the space does not list is a project under its
  `projects_dir`, which `kb create --new-project <name>` opens from nothing: that flag
  sets `repo`, sets `options.new_project`, and makes the card `attended` unless
  `--autonomy` says otherwise, because the first card on an empty repository decides what
  the project is. See [houses](20-houses.md).
- **keel card**: `derived.keel_card` (c-592, `keel/bosuncards.py`), on a personal card with a
  repo in builder mode (`derived.bosun`) only, and only in the deck's state document: who
  filed it (its `create` event's actor), Bosun's state (plan, queued, building, next, live)
  and whether the user's personal board shows it ([Bosun](96-bosun.md), "Keel cards on the user's board").
  A personal card with no repo is research, a plan, an errand or a capture, and its outcome
  gate is the user's read of the result: Done or Send back with a note ([the deck](40-deck.md),
  "Research on the deck"). So is any card whose `options.kind` is `research`, in either space
  (c-719). **A research card's outcome IS the research**: its record opens as a research
  outcome (`kind: research`), whose light contract (C26) is Findings, What it means, What is
  next and Evidence, the findings written there whole, with no separate report file and no
  link to one ([plans on the deck](47-plans.md); `docs/plan-format.md`, "A research card's
  outcome"). **The kind follows the role** (r1.F1, r2.F2, r2.F3; `planlint.follow_card`, run
  by `plangate.lint_file` at `kb stage planning` and `kb stage review` and at Bosun's approval
  check, by the plan and outcome pages and by the row's facts). A card's record (`context.md`)
  is an outcome: any other kind it names is read as `outcome`, held to the outcome's sections
  (with its Risk and its boards when it ships), and the mismatch is a C26 error, with two
  exceptions: `research` or `report` on a card that writes research (`planlint.writes_research`:
  a research card, `merging.is_research`, or a card with no repo, which ships no code), and
  `review` on a review card. A card's plan (its `plan_ref`, or the `--plan` at planning) that
  names any kind but `plan` is read as a plan, with a C2 error (a `context.md` is always the
  record, whichever caller asks). So no card skips its
  outcome's or its plan's contract by naming another kind; on the live board (2026-10-08)
  every record says `outcome`, or `review` on a review card, and every plan `plan`, so none
  lints differently. A record with NO frontmatter is the older markdown flow: `kb stage
  review` does not lint it at all (`plangate.contract_checks` returns before the lint), while
  Bosun's approval check reads it as an outcome and holds it to the five sections. A `kind:
  report` file that is neither a card's record nor its plan is held to the research outcome's
  four sections.
- **worktree path**: the adapter's answer for work, `state/worktrees/<id>` for a personal
  repo, or `<key>/trees/<id>` for a repo the install cloned ([onboarding](89-onboarding.md)). A cross-repo card's further repos become `--add-dir`s.
- **backlog**: a card that has sat at its OUTCOME gate longer than `backlog_days` (7).
  Date alone, nothing else: no cap, no ordering, no rank. A backlog card is not needs-you,
  so it leaves Attention and `kb needs-you` but stays findable through `kb list --backlog`
  and the deck's backlog chip. `options.backlog` overrides the date outright
  (`backlog` always, `active` never, `auto` hands it back). A plan gate never backlogs.
  **The clock starts again at the user's own action** (c-673, `Board.backlog_clock`): the date is
  the newest of the card reaching review and the user's newest own action on it since. Without it,
  a tap on a card long at review (a flow move the house does within
  a minute) leaves the card in the backlog the same day, gone from where the user is looking.
  The rule is about whether the user has attended to the card, so THE USER'S TAP COUNTS, WHATEVER BECAME
  OF IT: a Resume the user asked for that then failed still counts, because they were on the card
  and saw it fail. Nothing waits for a background send and nothing is undone.

  **What counts**: any event on the card, newer than its reaching review, whose actor is
  `human` (a tap in the deck, the user's `kb` with the user's token) or `voice` (`views.HIS_ACTORS`). At
  review those are a note, a `set`, an unblock, a mark on the outcome page, the user's answer to
  an ask by tap or by voice, a relay (Approve outcome queued to land, a tap held for a
  working house, a tap for a house on another machine), Stop session, the user's close of one
  idle house, a flow move (its grant and its "flow move asked" note), and Resume
  (`actions.act_resume`). A Resume tap that is refused because the conversation is open in
  a terminal (two live sessions for the card included), or because the card has no house
  or is done, writes nothing of the user's (two live sessions leave only the drain's note). A tap that resumes the house, tells it or is held for it
  leaves an event of the user's: the user's answer's note, the unblock or the held relay when the tap
  wrote one, and otherwise the note "resume asked from the deck" (`actions.note_asked`). A
  tap that fails with "resume failed", or with a refusal from the resume itself (no model,
  a voice hold), leaves that same note. The rare cases that still leave none are unchanged
  from before this card: the held relay or the unblock itself failing after the attempt,
  a harness call that times out, or the board refusing the note itself. A flow move leaves its own two. An event by a house, the drain, a hook, `cli`, Bosun or the
  talker never counts, however recent, so a house's note or the drain's bookkeeping cannot
  keep a card out; an answer the user gives Bosun in chat is recorded as Bosun's. Opening or
  reading a card writes no event, so looking alone moves nothing.

  **What is passed over** (`views.his_action`), two things written under the user's name:
  - the switch itself: a `set` of `options.backlog` alone (`auto` hands a card back to the
    date it had, not to today);
  - a pass over many cards, each write of which carries `bulk` in its data
    (`views.BULK_DATA`, from `kb relay --bulk` and `kb note --bulk`) or is a `set` of only
    a pass's own option. The passes are the outcome boards backfill
    (`bin/keel-outcome-boards --run`: its relay, and its `set` of `outcome_boards_sent`),
    the ship upgrade (its note, and its `set` of only `shipping` or `ship_now`), and Now's
    Close all idle (each card's note carries `bulk` beside its `closed-idle` mark, which
    means what it always meant). The drain carries a bulk relay like any other.

  **The known limit**: the clock trusts the actor the board recorded, and `kb --actor
  voice` is not checked against the user's token on this path (`cli.resolve_actor`), so a shell
  that names voice moves it.

  It is derived from the events on every read and nothing is stored: two lookups on the
  card's own index, made once per card and only for a card at its outcome gate.

  **A review card waiting in the INBOX backlogs too** (lane RC, `views.review_backlog`): when
  its pull request's last activity is older than its space's `review_backlog_days` (15,
  `[spaces.work]`). Last activity is `options.review_pr.activity`, the latest of when it was
  raised, the code host's last update (a push, a comment, a reviewer requested) and the
  moment the fetcher first saw a new head; the fetcher refreshes it on every poll and writes
  the days beside it, so a push or a comment brings the card out by itself and a quiet one
  drops back in. The override wins as for any card; the user's Review tap takes it out (a card past
  the inbox never backlogs this way), and its `backlog since` is when the pull request went
  quiet.
- **backlog since**: the instant the backlog rule counts from, set whether or not the card
  has backlogged, so the deck can say "at review 41 days". It is the one answer of
  `Board.backlog_clock`, read once and given to the rule and to the deck alike, so the
  deck's number and the rule cannot disagree: the newest stage-to-review event (an imported
  card's `created_at`), or the user's newest own action since. Not `updated_at`, which a house's
  note would move. `gate since` is still when the card reached review.
- **worker** (c-645): `options.worker`, `house` or `bosun`, the user's choice of who works a card
  the user may give Bosun; absent, the builder rule decides. Bosun's card is never startable
  (`views.bosun_builds`, [Bosun](96-bosun.md), "Who works a card").
- **archived**: `options.archived`. An archived card is never needs-you, never startable,
  never reconciled, and hidden from `kb list` without `--all`.
- **startable**: `assigned`, not blocked, not claimed (`options.claim`, below), and EVERY
  card its `after` names is at `review` or `done` (only `done` for a card whose repo lands on
  an integration branch: "The integration branch", above). A card the owner made
  independent waits for none of them, and a stacked one waits for its parent only until
  that card has a branch pushed ("Stacked or independent", below). Whether it can start here is the drain's question,
  not the card's: its space and whether its repo is on this disk, or can be scaffolded
  ([the drain](30-drain.md), "Where a card starts", `keel/where.py`).
- **voice hold**: `options.voice_hold` while it is live, which is when voice is talking to
  this card's house ([the talker and voice](50-talker-and-voice.md)). It is the one field a
  house may not set on its own card: a held card is skipped by the drain and by the Stop
  hook's nudge, so writing it would be a house making itself undrainable. `board.HOLD_ACTORS`
  is the mechanism (`voice`, `drain` and `human` only), and a house cannot claim another
  actor to get around it.
- **relays**: the card's pending `relay` events, oldest first (`derived.relays`): the
  human's taps that its house's drain has not carried yet, among them (c-598) a tap held for
  a house that is working until its turn ends.
  Pending is a `relay` no `carried` event names (below).
- **tracking**: this card has children, so it tracks them and works at nothing itself. It
  is the flag every reader that must not treat it as a working house looks at
  (`drain.holds_slot`, `drain.reconcilable`, `deckstate.houses_of`, the deck's word and
  `kb list`). `kind` is not this question, since it answers errand or house and a split
  never changes it; the stage is not either, because a tracking card borrows its children's.
- **parent stage**: a card with children is `review` when any child is, else `building`;
  when ALL its children are done it is `review` until it is closed (by the drain's next
  pass, or the user's Approve outcome while it waits at review), and `done` only then
  (`views.tracking_stage`, lane X, c-649).
- **tracking tally**: where a tracking card's slices stand, in the words every reader
  prints: `1 of 8 building, 7 waiting`. Null on a card with no children.
- **after** and **waiting for**: every card the `after` column names, as a list, and the
  ones of those not yet at `review` or `done`. The deck's "waits for" reads the second.
  `options.stack` changes the second and never the first ("Stacked or independent", below).
- **stack**: `derived.stack` (c-718, `keel/stacking.py`), None with no choice; else the
  choice and the card it is about (`on`), and for a stacked card what that card's own
  record says: its `branch`, the `repos` it works in (c-772: the card is stacked in those
  alone), whether it is `pushed`, its pushed `heads`, whether it has `landed` (done) or was
  `dropped` (archived, or gone), and the `base` it merges into.
- **tree**: on a tracking card, its outline (`keel/tree.py`, "The card tree" below); null
  on any other card.
- **follow ups**: the cards whose `from` is this one, oldest first. The other end of the
  stored field, and the one derived flag that decides nothing: it touches no gate, no
  stage, not `startable` and not needs-you, at either end.

## Two relations: a slice and a follow-up

A card can name another card in two different ways, and they do different things.

| | What it says | What it does to the card it names |
|---|---|---|
| `parent` | this card is a SLICE of that one | that card becomes a **tracking card** |
| `from` | this card CAME OUT OF that one | nothing at all |

`from` is the one to reach for when work is filed that this card is not doing: a follow-up,
a bug found on the way, a second repo's half someone else will take. `kb create --from <id>`
sets it, `kb set <id> from=<id>` moves it and `from=` clears it, the referenced card must
exist (across spaces is fine: a personal card's follow-up is often a work card), and
`kb show` prints it at both ends, `from: c-286` on the card and `follow-ups: c-299` on the
origin.

## Big cards: split at the plan gate

A card too big for one house splits **outward** into child cards, decided on the plan
surface and never later. `kb split <id> --slice "title|brief[|after-title|...]" ...` creates
one ordinary card per slice with two extra fields, `parent` and `after`. A slice takes its
parent's repo, model, autonomy and topic, and the options the parent stated ("A slice
starts as its parent would", above). A slice may name
several earlier slices after its brief (`"import|brief|export|host"`) and then waits for
all of them.

**A slice names its own repos at the split** (c-771). A parent that names several repos
hands every one of them to each slice, and a slice is cut a worktree in each repo it
names, one it never touches included. A `repo=<key[,key]>` part on the slice says which it works in
(`--slice "the api half|brief|repo=api"`): the slice gets exactly those, with the
provenance `stated`, and a slice with no such part takes the parent's as before, with
`inherited`. Two checks, and either refuses the whole split with no slice filed. Each key
is one the space can open, as `kb create --repo` asks (`cli.refuse_unknown_slice_repos`),
and the stated repos are the parent's or fewer (`cardspec.slice_repos`): "slice 'B': docs is
not a repo of c-12 (api, web); a slice works in its parent's repos or fewer". A `repo=`
that names nothing is refused too, since leaving the part off is how a slice inherits.
The repos a slice keeps are stored in the PARENT's order, whatever order was typed
(`repo=web,api` on a parent `api,web` is `api,web`): a card's first repo answers its
one-base rules (its integration branch, the brief's single base, the stage check), so a
slice's first repo is always its parent's first among those it keeps.
Every rule the split asks of a slice's repo (its base, the browser, its worker, its stack)
is asked of the repos it ended with. Any actor allowed to split may state them: narrowing
grants nothing.

How a `--slice` is read (`cli.parse_slice`): the first part is the title and the second
the brief, whatever they spell. A part after them that is exactly the title of an earlier
slice in the same command is an after-title, whatever it spells. Any other part that
starts with `repo=` or `stack=` sets that (`cli.SLICE_PARTS`, the last of each winning),
and every part left is an after-title. So an `=` in a title, a brief or an after-title is
only text, and a slice titled `repo=api` can still be waited for.

The deck's Split draws the parent's repos as chips on each slice's row when the parent
names more than one, all chosen to start with; the last one cannot be taken off. A slice
left with fewer sends them (`{"repo": [...]}`, folded to `|repo=` by
`actions.split_argv`), and one left with all of them sends none and inherits. The server holds
the page's rule (`actions.split_argv`): a `|` in a title, a brief or an after-title, or a `|`,
`,` or `=` in a repo key, is refused, since a slice travels as one `|`-separated text. A house's
split after its plan is approved states them in its own `kb split`: the plan says which
repos each slice needs, and the house's brief asks for it (`prompts.CHILD_CARDS`, and
`planbrief.SPLIT_ROWS` in a stacking space). The approve keeps no repos on the card: the
check at the split is the same whoever runs it.

The parent becomes
a **tracking card**: its stage is derived from its children, it has no plan gate of its
own, `kb stage` refuses it (except the moves below), and it is never startable. It has no
outcome gate of its own either: the drain closes it when every slice is done ("A tracking
card is closed by the drain", below). The drain starts
a child only once every card its `after` names has reached `review` or `done` (`done` on a
repo with an integration branch), so a dependency is an order and nothing more.

### A tracking card holds no house slot, and its own session is ended

A tracking card has nothing left to do, and the STAGE cannot see that: it is its children's,
so it reads `building` for as long as any slice builds. The drain therefore reads
`derived.tracking` and not the stage:

- **It holds a pool slot only while its own session is doing something** (a `busy` agent
  row, or a resume whose turn has not ended). Otherwise a card split into slices, its house
  stopped, holds one of the house slots as an idle parent while one house is
  actually working: every pass logs `house pool full at <n>; <id> waits` and it would
  hold the slot until the last slice finishes (c-277).
- **It is never reconciled**: not resumed when its session is gone, not nudged at its
  turn end (the Stop hook says so, c-292), and never blocked for
  sitting at `building`. There is no work on it to continue. The block is not hypothetical.
  Once an idle parent's session is stopped by hand, the next pass finds no agent row
  for it at `building` and, without this rule, records `house exited twice at building` on a card whose
  slices are doing the work. Unblocking one is `kb unblock` and nothing else:
  a block writes only `blocked_reason`.
- **Its idle session is stopped once**, with a note on the card saying so
  (`drain.retire_tracking`). The slices carry the work, the process holds a few hundred MB
  for nothing, and a later resume mints a fresh session anyway. A busy session is never
  touched, and one session is retired once, not every pass.

### A tracking card is closed by the drain (lane X, c-649)

A card split into slices, with every slice done and
its house's last session ended, would sit stored at `building`
with needs-you false, so the deck shows it nowhere and only a raw board read
sees it (c-277). Brought to the user's outcome gate instead, it
sits there with no outcome at all, asking the user to approve again what they approved slice by
slice (c-628). By the user's decision, a tracking card has no outcome gate of its own.

- **Every slice done: closed to done, once.** Each drain pass (`drain.close_tracking`, the
  rule in `keel/trackclose.py`) closes a tracking card it owns whose unarchived slices are
  all done straight to `done`, from any stage, through `Board.close_tracking`: one `stage`
  event by the drain whose note says why (`every slice is done; each passed its own outcome
  gate`). Nothing is merged, landed or published: each slice did that when the user approved it.
  A card with no children is untouched. The log line says `closing=N`.
- **Not while the user is in the middle of it.** No close while the card is blocked, voice or a
  drop-in holds it, or an ask about it is open (the holds `drain.retire_tracking` skips);
  the first pass after that closes it.
- **The rollup is its outcome, on every close.** `Board._close_tracking` is the one close,
  the drain's and the user's Approve outcome's alike: inside its own write it reads the slices
  again (a slice reopened since the pass looked refuses it), drafts
  `state/cards/<id>/outcome.md` beside its place, makes the move with it as the card's
  `output_ref`, and only then renames the draft into place, so a refused close leaves no
  rollup. The deck's output link opens it. A disk error is logged for that card and the
  pass goes on. It is an outcome in the plan format
  (`kind: outcome`, `change: none`, since the card itself lands nothing, so C33 does not
  hold it) and passes `kb lint` with the five outcome sections and a Risk. Its summary line
  says every slice passed its own gate; its Evidence has one entry per slice: id and title,
  where it landed (the slice's `options.landing` sha and its merge into the integration
  branch, else how its approve ended it: `approved, published: ...`, `staged done by
  <actor>`), the first paragraph of its own outcome (`state/cards/<slice>/context.md`, else
  an `output_ref` that is a file), and a link to that outcome. A slice's own outcome is its
  `output_ref` when that is a file in its card folder (a tracking slice's own rollup), else
  its `context.md`. What it quotes is made safe for the list: no em-dash, a relative link
  made absolute against the slice's folder, and a cut at a sentence end that never splits a
  code span or a link.
- **One already at review closes on the next pass.** A card the drain brought to the user's gate
  under the earlier rule, or one the user brought back with Back to your gate,
  is closed the same way from `review`. While it waits there (until its next pass, or longer while the user holds it) it still
  reads at the user's outcome gate, and their Approve outcome still closes it:
  `Board._approve_outcome` moves it to done and never calls the publish callable it was
  handed, and the approve event carries `tracking: true`. Every path agrees: the deck's tap
  goes straight to `kb approve` (no landing), and returns the card unchanged when the drain
  closed it first; `landing.mergeable` is false for a tracking card (so no `land` relay and
  no pre-run with `merge_queue` on), a `land` relay is refused on the board, and the work
  adapter's `publish` returns `{"published": "nothing", "kind": "tracking"}` if it is ever
  reached. Approve outcome is refused while any slice is not done.
- **A slice not done: it keeps waiting.** Nothing moves a tracking card while any
  unarchived slice is short of done.
- **Send back puts it back to tracking.** From review to building, with the user's words as the
  note. There is no house to resume, so nothing is resumed, and the drain does not close it
  straight away: only once a slice has reached done after the user's Send back (a reopened slice
  finishing, or a new slice filed and finished).
- **Back to your gate, by the user's tap (r-19, c-540).** A Send back with every slice done has
  no slice left to change, so the drain never closes it, while every reader shows it at
  review (`tracking_stage`). `derived.regate` says so (tracking, every tracked slice done,
  stored stage not review, shipping or done, not archived), and the card pane's primary
  action is Back to your gate: the `stage` verb to review as the user, which
  `Board._refuse_tracking_move` allows. The drain's next pass then closes it from review.
- **A slice leaving done takes it back, even after the close.** While it waits at review,
  or once the drain has closed it, a slice reopened, sent back or taken to shipping by the
  sync, or a new slice filed under it, moves it back to `building` with a note naming what
  is not done (`unclosed=N` on the log line), and the drain closes it again, with a fresh
  rollup, when every slice is done again.
- **The moves are the board's.** `Board._refuse_tracking_move` allows a tracking card
  exactly two stage moves: to `review` when every slice is done, and back to `building`
  from `review` or from `done` while a slice is not done, each by the drain or by the user only
  (`TRACKING_MOVERS`). `done` is never a stage move: `kb stage <id> done`, even with
  `--actor drain` from a shell, is refused (naming the slices not done, if any). The close
  is `Board.close_tracking` (`TRACKING_CLOSER`, the drain), which no `kb` verb reaches, or
  the user's Approve outcome at review; every other stage move is refused as before.

Where a stage would be printed, a tracking card says that it is tracking and how its slices
stand: `kb list` and `kb show` print `[tracking: 1 of 8 building, 7 waiting]` from
`derived.tracking_tally`, and the deck draws the same sentence ([the deck](40-deck.md)).

`kb split` is the deliberate way to make a tracking card. The other way, `kb create
--parent <id>`, is **refused on a card that is being worked**: one with a `session_id`, one
a drain has claimed, or one at `planning`, `building`, `review` or `done`. A card that is
already tracking is exempt, since another child changes nothing about it, which is how a
phase card is added under a plain inbox parent like c-278. The refusal names `--from <id>`
for a follow-up and `kb split` for a real split. `kb set <id> parent=<id>` goes through the
same refusal: it makes a tracking card as surely as `create --parent` does.

**An archived card is never a parent** (c-427). c-014 was archived in July, a card was
filed under it, and it came back on the board as a tracking card. `create --parent` and
`set parent=` refuse an archived card, even one that already has children (the refusal is
checked before that exemption), and name `--from` for work that came out of it. The
derivation agrees: an archived card tracks nothing, and an archived child is not a slice
still in play, so `derived.tracking`, the parent stage, the tally and the board's own
tracking refusals (`kb stage`, `approve outcome`, the Stop hook, a claim) all read the live
children only (`views.tracked`). It is a mechanism and not a sentence in
the house brief because cards lose their gate to it: one
loses its plan gate, one cannot stage to review, and one is nudged at `building`
with nothing left to stage (c-295, c-286, c-292).

A parent is changed or cleared with `kb set <id> parent=<id>` and `kb set <id> parent=`,
recorded as a `set` event like any other field. The target must exist, a card may not be
its own parent, and a parent that is already below this card is refused as a cycle. It
also answers to every check `create --parent` has (J-2): a parent in another space is
refused, and so is one the card waits for, through its afters and its own slices however
far down (`Board._refuse_waits`, the walk `after` uses), since the new parent would then wait
for the card and the card for it. An `after` given in the same `set` is checked against
the new parent. When
the last child leaves, the former tracking card is an ordinary card again at its stored
stage, and `kb stage` works on it. An empty value CLEARS a link field rather than storing
the empty string (`board.LINK_FIELDS`), which is the state c-294 is in on the live board.

**Inward** parallelism is different and needs no card: a house fans out with subagents
inside its own session, on one worktree, ending in one pull request. The harness runs
them and Keel does not know they exist.

Cross-child conversation is deliberately not built. A child that needs a sibling changed
writes a note on it and blocks with the reason.

## Stacked or independent: a waiting card and the card it waits for (c-718)

A card whose `after` names another waits for it, and is cut from its base without that
card's code. In a space whose pack stacks (`stacks = true` under its `[capabilities]`,
[packs](62-packs.md); the work pack does), the owner decides per waiting card, and the card
records it as `options.stack` (`keel/stacking.py`):

| `options.stack` | Cut from | Its change aims at | Starts when |
|---|---|---|---|
| absent | its base | its base | every card its `after` names is at review or later (as before) |
| `independent` | its base | its base | at once: its `after` holds nothing up |
| `stacked` | its parent's branch | its parent's branch | its parent names its branch and has it pushed |

The PARENT of a stacked card is the one card its `after` names: a stacked card waits for
exactly one, and it must be an ordinary card (not tracking, not research) that works in
at least one repo the stacked card does, merging into the same base (r1.F8, r1.F12; c-772:
one repo in common is enough, and a card that shares none is refused). "Pushed" is
read off the parent's own card, never a second record: it names its branch
(`options.branch`) and records a change (`options.pr` or `options.prs`, which its house
opens once its branch is on the remote) or is at review, shipping or done
(`stacking.pushed`). The waiting rule lives in `views.waiting_for`, so `startable`, the
tree and the deck's "waits for" all follow it, and `derived.after` still names the parent.
`derived.stack` also carries the parent's base, and a parent that is done counts as landed
whatever became of it after, so one archived once it merged is never "dropped" (r1.F5).

**Stacked is per repo** (c-772). The table's `stacked` row holds in the repos the card and
its parent both name (`derived.stack.repos` is the parent's list). In a repo the parent
does not name, the parent has no branch, so the card is cut from its own base there and its
change aims at that base, exactly as a card with no choice: `stacking.base_of(card, repo)`
answers None for that repo, before the parent lands and after, and the caller's own rule
stands. "It merges where its parent merged" (r1.F12) is likewise a rule for the repos the
parent named: the parent merged nothing anywhere else. `stacking.split_repos` gives the two
lists. The choice is read back saying which is which: recording it on such a card (at
create, by `kb set`, at the split, or by the owner's Approve plan) writes one note, `this card is stacked
on <parent> in <repos>; in <repos>, which <parent> does not work in, it is cut from its own
base and its change aims at that base` (`stacking.spread`); a card whose repos are all its
parent's gets no note.

**The branch a stacked card is taken against** is its parent's while the parent has not
landed (`stacking.base_of`, from `derived.stack.branch`, the parent's `options.branch`):
`house.target_of` (the brief's review base, its rebase line), the stage check's "contains
the base" (`stagecheck.base_check`), `keel check` (`keel/fixcheck.py`), the plan lint's
claim check (`plangate.claim_base`, r1.F7), the shipping watcher's base
(`shipping.base_of`) and a fresh start's record all read it first. So its review shows only
its own commits, and it can never merge first. Once the parent is done, the card's own
base answers, else the base its parent merged into.

**One rule for a card's base in a repo** (c-772): `merging.base_in(cfg, card, key)`. In
order: the stacked base in that repo, the card's own base (`merging.card_base`), the repo's
integration branch, the branch its worktree was cut from (`merging.cut_from`), the repo's
usual branch (`merging.usual_branch`); None when none answers, never a guess and never
another repo's base. It lives in `keel/merging.py` because every step after the first is
that module's already, and the house, the shipping pass and `keel check` all import it.
Each reader asks about the repo it is acting on:

- `house.target_of(cfg, card, key)` is that rule (with `main` where it has no answer, as a
  card's one base always was), `key` defaulting to the card's FIRST repo: the brief's review
  base, its rebase line, a flow move's `{base}`.
- `keel check` (`fixcheck.own_bases`) hands the prep a base for EVERY worktree of a card
  stacked in only some of its repos, each by the rule. A worktree whose repo it cannot tell,
  or whose repo has no base the rule can read, refuses the check with a sentence naming it
  (`fixcheck.NO_REPO`, `NO_BASE`): an apart worktree never takes the stacked base by default.
- The shipping pass (`shipping.repo_base`, `tree_base`, `shipstep.restack`) keeps
  `shipping.base_of` for the card's first repo, where the record names the pull request's
  own destination, and asks the rule for any other repo of such a card, so its conflict read
  and its restack entry hold in a non-first repo with no `options.base` on either card.
- The claim check (`plangate.claim_base`) asks the stack for the worktree's repo, then
  reads that worktree's own base as it always did.
- The stage check (`stagecheck.base_check`) reads the first repo's worktree against the
  first repo's base.

Where a house reads one base, the text says the rest, whenever the card's repos really have
different bases (`house.repo_bases`: the rule asked per repo, on a card stacked in only
some of them), before the parent lands AND after: the brief's review section ends with a
paragraph (`house.stack_apart`, worded by `review.brief.per_repo_block`) saying where the
card is, or was, stacked, naming every repo's base, and giving the flag that hands a
worktree a base of its own (`keel-review prep --worktree-base <worktree> <base>`, on every
prep, `--since` too); a fresh start's record names each repo's base; and the refusals that
print a prep to rerun say to add the brief's `--worktree-base`s (`stagecheck.per_repo`,
`stamp.earned_why`). A text that names one base and no repo (the shipping batch's REBASE item, the drain's
"parent merged" message) adds `stacking.OTHER_BASE`, "Another repo of this card may have a
different base.", only for a card that has a repo its parent does not name. A flow move's `bases`
(`flows.based`) still reads the card's own `options.base`, by decision: a move names the
team bases it fits, and a stacked card lands on its own base once its parent has. What the
pack does with it (where the worktree is cut, where the change aims, retargeting it when the
parent lands) is the pack's ([the work adapter](60-work-adapter.md)); what the drain does
when the parent lands, moves or is dropped is [the drain](30-drain.md)'s, "Stacked cards".

**Who records it, and what else the owner alone moves** (r1.F1, r1.F2). `options.stack` is
one of `board.HIS_AT_CREATE` (refused to every actor but `human` at create, in a slice, and
after). On a card that carries a choice, its `after`, its `repo` and its `options.base`
decide what it is stacked on, so a change of any of them is the owner's alone and is checked
again (`Board._refuse_stack`). The PARENT's `repo` decides it too (c-772: a card is stacked
only in a repo its parent names), so a set of a card's `repo` looks at the cards stacked on
it (`Board._refuse_repo_under_stack`): one that would be left sharing no repo refuses the
set, naming that card and the way on (make it independent first, or keep a shared repo), and
each one whose stacked and not-stacked repos change gets one note saying the new split. `options.base` on any card is changed after create only by the
owner's actors (`board.OWNERS_OPTIONS`, `WORKER_SETTERS`: the token, voice, the talker):
refusing the house actor alone was not enough, since a house shell that drops `KEEL_CARD`
runs as `cli`. A card's `options.branch` is NAMED ONCE (`board.ONCE_OPTIONS`): the worktree
verb writes it at the first cut and the shipping sync when it finds one, both only when it
is missing, and a different value after that is the owner's alone. The board cannot tell
which house a `kb` runs for, so "only its own house" could not be a mechanism; written once
is. `options.cut_from` (the usual branch each repo of the card was cut from, which the
landing prefers, [onboarding](89-onboarding.md)) is the drain's alone (r2.D1,
`board.CUT_FROM_OPTION`): `kb set` refuses it to every other actor (a house, Bosun, the
owner), create, split and a row insert refuse it outright (`board.RESERVED_OPTIONS`), and a
name in it that is not a branch name by the bases' own rule (`bases.branch_problem`) is not
read (`merging.cut_from`). A re-cut by the drain overwrites that repo's entry, so a card cut
again after the team moved its default lands where it was cut this time (r2.D3). The shipping sync (`keel/shipsync.py`) writes as the drain, so on a card with a choice
it records the pull requests, the branch, the worktrees and the move to shipping, but never
grows `repo`: a pull request found in a repo the card does not list is recorded and the
owner is asked, in one note, to add the repo with `kb set` (r2.F2). The board refuses a value that is neither word, a space whose pack does not stack
(`Board.stacks`, `Config.stacking`), a card that waits for nothing, a stacked card that waits
for more than one, and a parent the card cannot stack on (`stacking.problem`,
`stacking.parent_problem`). `null` clears it, and a later change is a plain `kb set <id>
options.stack=...` by the owner: no other flow.

**Where it is decided: the split, first** (c-718's addition, the owner's word). A split is
where most waiting cards are made, so a split carries each slice's answer, and every slice
has it from the start, whether or not it ever stops at a plan gate:

- **The deck's Split** (the owner's own split, `K.openSplit`): a slice that waits for an
  earlier one gets a second picker beside its "after", `stacked on it` (first, since a slice
  is made to wait because it needs the other's work) or `independent` (it starts now), shown only in a
  stacking space (the state document's `spaces.<name>.stacks`). The answer rides on the
  slice as `|stack=<choice>` (`actions.split_argv`, `cli.parse_slice`).
- **A slice's own repos and its answer go together** (c-771, c-772). A stacked slice is
  cut from the branch of the slice it waits for in the repos the two share, so it needs at
  least one in common (`stacking.parent_problem`), and the check reads the repos each slice
  ended with. A slice that states `repo=api` stacks on one that states `repo=api`. One that
  keeps `api,web` stacks on it too, in api alone: in web it is cut from its own base, and
  the split says which is which, in its note (`'export' stacked on c-13 in api; in web,
  which c-13 does not work in, it is cut from its own base and its change aims at that
  base`), in the slice's own note and under the slice's readback from `kb split`
  (`cli.stack_aside`). One that shares no repo with it (`repo=web` on a `repo=api` slice) is
  refused or left without a choice by the next rule ("c-13 works in api, not in web, so it
  has no branch there to stack on"). Once the slice exists and
  carries a choice, its `repo` is the owner's alone to change, as on any such card
  (`Board._refuse_stack`).
- **A house's split, after the owner approved its plan.** A house splits its card with `kb
  split` once its plan is approved; a split card is a tracking card with no gate of its own,
  so the approve IS where the owner confirms the split, and where the answers are given. The
  plan's ONE `stack` batch carries a row per slice that waits for another, `s2: <its exact
  title> (after <the title of the slice it waits for>) | stacked | <why>`, with the house's
  recommendation and a line of why, and the breakdown is drawn once on a board
  ([plans](47-plans.md)). The owner confirms or flips each row, and `kb approve <id> plan` by
  the owner keeps those answers on the card being split as `options.split_stack`, `{title:
  {choice, on}}` (`stacking.record`; one of `HIS_AT_CREATE`, so no house writes it). The
  house's `kb split` then gives a slice its approved answer ONLY when the slice waits for
  exactly the slice the owner approved it on (r2.F1, `stacking.split_answer`), so the house's
  split cannot pick what a slice stacks on; otherwise the answer is left off and said. Titles
  compare with their spaces folded (`stacking.title_key`), and every approved title no slice
  took is said too, never dropped. The split's one note (`Board._slice_stack`) says what each
  slice got.
- **Each slice's answer is checked like any** (r1.F9): one the owner typed on the slice that
  cannot stand refuses the split, naming the slice; one approved at the plan gate that cannot
  stand (a slice that now waits for two, say) is left off and said, since the house running
  the split cannot change it. A slice that waits for nothing starts at once and takes none.
- **A card stacked on the card being split is blocked once** (r2.F5,
  `Board._block_stacked_on`, in the split's own write): a tracking card has no branch of its
  own, so the sentence (`stacking.SPLIT_UNDER`) names it and says to stack the card on a slice
  or make it independent; `stacking.pushed` is never true for a tracking card either. It
  is a block like any (a re-offer ask on it is dropped with a note, `_drop_reoffer`), and a
  card already blocked for another reason keeps that block and is named in the split's note. And the
  approve that keeps slice answers does not stack a waiting card on the card it will split:
  such a row is said as not recorded.
- **An autonomous card's split** has no gate, so no confirm step: its slices wait as before
  until the owner gives an answer with `kb set`, or the slice they wait for has a plan of
  its own that proposes them.

**The plan gate, for waiting cards a split did not make.** In a stacking space the brief's
plan bullet (`planbrief.stacking_block`) names the cards that already wait for the one being
planned (`stacking.waiting_cards`, ids and titles, r1.F14) and asks for a row each in the
same block, its id as the row. A row whose id has a card's shape (`c-NNN`,
`stacking.CARD_ROW`) is always a card row: one for a card that does not wait for this one is
said as not recorded, never kept as a slice answer (r2.F8). `kb approve <id> plan` by the owner writes each row on its
card as `options.stack`: the owner's pick this round, else the plan's recommendation, except
that a card already holding a choice keeps it unless the owner flipped its row this round
(r1.F13). One note on the approved card says what was recorded; a choice a card cannot take
is named in a second. Nothing in the recording can fail the approve, which has already moved
the card: a plan that cannot be read, or any other failure, is one note
(`cli.record_stacking`).

## The card tree

`keel/tree.py` answers three questions about the two links, and every reader asks it
rather than working it out again: `kb tree`, the deck's outline and voice read one
computation, `derived.tree`.

**More than one `after`.** The column is one TEXT field holding ids separated by commas,
so a value written when a card could wait on only one card is already a list of one and
nothing migrated. `kb create --after` repeats (or takes commas), `kb set <id>
after=c-311,c-313` replaces the list and `after=` clears it, and a split slice names
several earlier siblings. Every id must exist; a card waiting for itself, or for a card
that already waits for it however far down, is refused as a cycle (`Board._refuse_after`),
since every card on a cycle would wait for ever. The walk goes through a tree's slices as
well as its afters, because a tracking card reaches review only when its slices do: a slice
may not wait for its own parent or any card above it, and a card may not wait for a tree
one of whose slices waits for that card. `kb create --parent P --after ...` runs the same
check as if the new card already stood under P, and a slice is filed in its parent's space
(`--parent` across spaces is refused; `--from` is the link for related work elsewhere).
`after` names several cards (below). While it could name only one, a brief had to say
in prose which other slices should be done first (c-302 ended that).

**Several afters are behind a switch: `[keel] multi_after`, off by default and on in the shipped example (`etc/shipyard.example.toml`).** Code from
before c-302 reads `after` as ONE id and fails on the whole board when it meets a comma
list. With the switch off, one id in `after` is written as always and several are refused
by name (`create`, `set` and a split slice alike); a row that already holds several is still
read. Switch it on only once every running process (the drain and the deck) has been
restarted on this code.

**The outline.** A tracking card's slices in STEPS, not indented under one sibling: a
slice's step is one more than the longest chain of waits inside the tree above it, which
gives a slice waiting for two siblings one place to stand. A wait on a card outside the tree
is shown on the slice and counts no step. Each slice carries what it still waits for,
`next` (not started, not blocked, nothing left to wait for: it could start now, or would
once assigned) and `unblocks N`, the unfinished slices downstream of it directly or
through others, which is how the user picks the slice that frees the most when assigning one
by one. Within a step the slices keep queue order. The follow-ups filed out of the card
are listed apart, never as slices. `kb tree <id>` prints it as plain lines the talker and
voice can read out.

**Assign the tree.** `kb assign <id>` on a tracking card moves every unassigned (inbox)
slice under it to `assigned` in one transaction, grandchildren included, and says what
that does: `4 assigned: 1 starts now, 3 wait; 4 stop at a plan gate first`. `--dry-run`
says the same and writes nothing, which is what the deck's sheet shows before the user confirms.
The drain then follows the tree by itself, since a slice still waiting is not startable,
and an attended slice still stops at its plan gate. On a plain inbox card it is the same
move `kb stage <id> assigned` makes. Slices filed later are NOT included (the user's answer at the
c-302 plan gate): a later child is a new decision, and the outline marks it not assigned.
`kb split` still files its slices at `assigned`, since approving a split is the
assignment; Assign tree is for slices filed later with `--parent`. `--ids a,b,c` assigns
only if the set to assign is still exactly those (the deck's confirm sends the ids its
preview showed, so a slice filed in between is refused with a reason rather than assigned
unseen). The outline's `unassigned` is that same recursive set, so a nested tree's count
and the button agree.

**Only the user orders or assigns.** `kb next` and `kb assign` (and `tree.to_front`,
`tree.assign`) refuse every actor but `human` and `voice`: a house, a drain or a plain
`kb` with no token cannot reorder everyone's queue or spend houses by the tree. The talker
runs them as `--actor voice`. `kb next` also refuses a done or archived card.

**The queue.** The order the drain takes startable cards (`tree.queue_key`): a card's
top-level tree's place, then its own place inside that tree, each one its `rank` when the user
has moved it and the order it was filed in otherwise. A whole tree holds ONE place.
`kb next <id>` puts a card in front of its peers (a slice among its siblings, anything
else among the top-level cards) by giving it a rank below theirs, and `--clear` hands it
back; a second `next` on a card already in front records nothing. `kb queue` prints the
queued cards (assigned, working, unarchived) in that order with why any is not starting.
No priority levels, on purpose: levels rot until everything is high. A place never beats a
dependency: the queue orders what is startable, and a card still waiting is not.

## Topics

`topic` is a free grouping word. The deck's composer infers it from the title and `kb set`
changes it; slices inherit their parent's, and so does a follow-up filed with `--from`. The deck groups and filters Cards by it, and
the state document carries each space's distinct topics. Searching transcripts across
sessions is a later card, not this field.

## Where the record lives

`state/cards/<id>/`, outside every worktree, so it survives the worktree being reaped:

- `plan.html` or `plan.md`, pointed at by `plan_ref`
  (always an absolute path, c-574: `kb stage --plan` and `kb set plan_ref=` resolve a
  relative one, trying the cwd, then
  the card's own directory, then the Keel home, pass over a file inside a worktree (it
  would be reaped with it), and refuse one that names no file elsewhere
  (`plangate.absolute_plan_ref`); a ref stored relative before that is read against the
  Keel home, never the reader's cwd (`artifacts.local_path`))
- `context.md`, six headings: Where it stands, What is next, Why this shape, Open
  questions, Evidence, PR body
- `assets/` for screenshots the context embeds
- `settings.json`, the house's hooks file
- `brief.md`, what the house was given
- `scratch/`, when a house makes one: throwaway work (a copy of a repo, a trial run, working
  notes). It is not backed up: the keel set leaves the folder out whole (c-752,
  [backup](85-backup.md)), so anything worth keeping goes in the card's directory proper

Notes, sign-off, the pull request and the story are events on the card. The transcript is
Claude Code's, under the space's config dir, reachable through `session_id`. A merged card
is not finished for the purpose of coming back to it: Drop in is a card action at any
stage, including `done`, where it resumes the card's conversation or, when that is gone,
opens a fresh session on the card's record (c-787, [the deck](40-deck.md), "On a done card").

## The verbs

`kb` is the board CLI (`bin/kb`, or `keel kb ...`). Every verb prints JSON with `--json`,
human text otherwise, and exits non-zero with a one-line reason on refusal. The actor is
`house` when `KEEL_CARD` is set, `human` when `KEEL_TOKEN` matches `state/human.token`,
else `cli`.

```
kb create   kb list     kb show     kb set      kb stage    kb approve
kb note     kb block    kb unblock  kb backlog  kb split    kb needs-you
kb tree     kb assign   kb next     kb queue    kb rereview kb verdict  kb ship
kb event    kb stop-check           kb import-harbor        kb session   kb claim
kb relay    kb carried  kb land     kb repos    kb help
kb flowpush kb flowmove kb flowinfo
```

`kb flowpush <id> <branch> [--pr <branch>]` (c-641) is a house's one way to push a shared
branch of its space's flow, only while the user's tap's grant names it; `kb flowmove <id> <move>` is
that tap made on the user's word through Harbor (`--actor voice` with the user's token); `kb flowinfo
<id>` is what both read, judged where the board is. All three are in [flows](64-flows.md).

`kb set` that changes nothing records nothing: when every field it names already holds
that value (options compared as JSON), `Board.set_fields` writes no `set` event and leaves
`updated_at` alone. The backup's hourly job re-stating an open notice with the same words
put an event on the card every hour until it did (c-440).

`kb repos [--space <space>]` is the read that answers "which repo". It prints one line per
repo key a card may name, per space: the `[spaces.<s>.repos]` table in the install's `config.toml` and the
git repos directly under that space's `projects_dir`, which are the two things
`Space.repo_path` resolves. It exists because whoever files a card has to offer the user the
choices rather than recite repo names from memory (the talker and the voice do, see
[the talker and the voice](50-talker-and-voice.md)).

`kb help` prints one line per verb from the same `cli.VERBS` table argparse is built from,
which is why a house's "What you can do" block can be generated and cannot drift.
`kb help <verb>` prints one verb's full usage.

### Claims

`kb claim <id> [--host <name>] [--release]` is a drain's verb, never a house's (the brief
leaves it out). In one transaction it takes a startable card for the drain on `host`
(default: this machine's name, `config.default_host`) and records `options.claim =
{host, at}` and a `claim` event. A claimed card is not startable, so a second starter
never starts it too: whichever claim commits first wins and the other is refused with who
holds it. Claiming again is a no-op, and a claim under another host name (the retired
box's, or this machine's before a rename) is taken over under this one with a `claim` event
naming the old host (c-622): Keel runs on one machine. Two starters are kept to one house
by the card's lock in `house.launch` ([houses](20-houses.md)).

The claim stays on the card once the house starts, as the record of which host runs it. `--release` hands it back (a drain only its own host's, the human any), a stage move
back to `assigned` clears it, and the deck's Retry releases a claim on a card still at
`assigned`, which is how a card whose claim went stale is freed. Every drain
claims before it starts a card ([the drain](30-drain.md)).

`kb session <id> --set <uuid> --resumed <prompt>` records a resume: one verb writes the `resume` event (the drain's
once-only mark) and, when the resume minted a new session, that session and its
`--app-link`. `Board.record_resume` does the same for the drain.

### Relays: a tap for the drain to carry

`kb relay <id> resume|stop|close-idle|start|land|rotate --to <host> [--prompt <text>] [--sha <sha>] [--bulk]` is the human's alone (the
token; `--bulk` marks one of a pass over many cards, which the backlog clock passes over) and is how the deck asks this machine's drain to act on a house (the drain, not the deck, owns
the harness session): it records a `relay` event naming the host, the prompt, and the session the card had
at the tap. `kb approve <id> plan` and `kb stage` take `--relay <prompt> --to <host>`, which
records the move and a `resume` relay in one transaction. `kb carried <id> <relay>
[--superseded <why>]` is a drain's alone (`--actor drain`) and marks one carried BEFORE the
drain acts, so it is carried at most once; a second `carried` for the same relay is
refused. A `kb` that writes a relay kicks the drain it names at once (c-598, [the
drain](30-drain.md), "The kick"). `kb land <id> --relay <n> [--published <text>]` is a drain's alone too: it
finishes an Approve outcome the drain carried as a `land` relay (below), moving the card to
done with an `approve` event that names the relay and the landed sha. It is refused unless
that relay is the human's, a `land`, and taken, the card is not blocked, and the worker
recorded `options.landing` as `landed` with a sha FOR THAT RELAY: one relay, one outcome, so
a refused landing can never be finished afterwards. A card whose space has an adapter is
refused both a `land` relay and `kb land`: it publishes through its adapter. None of the three is in a house's brief. The rest is
[the drain](30-drain.md), "Relays".

### `kb` opens the local board

`kb` always opens this machine's board (`keel/cli.py`, `board.open_board`); nothing sends
its verbs to another deck. Every handler in `cli.py` returns its payload and every `VERBS`
row renders it. The deck runs its own `bin/kb` under the actor's environment (`--actor`,
`KEEL_CARD`, `KEEL_TOKEN`), so the actor rule above decides as it would in a terminal: a
house is `house`, a drain passing `--actor drain` is `drain`, and `human` needs the token.
A body with a `caller` posted to the deck is refused (`actions.refuse_caller`): every action
is the user's, proven by the deck page's cookie ([the deck](40-deck.md), who may act as the user). `kb
event` and `kb stop-check` read a hook's JSON payload on stdin, and `set` fields and
`--option` values are parsed once, as typed. A `[keel] board_url` or `KEEL_URL` left in an
old config is ignored with one warning (`Config.warnings`).

## How to change it

- A new field: add the column to `keel/board.py`, add its `ALTER TABLE` to
  `board.MIGRATIONS`, and say what it means here. Prefer an `options` key: it needs no
  migration and the adapter declares how the deck draws it.
- A new derived flag: it belongs in `keel/views.py`, which attaches `derived` to every
  card read, and in the "Derived, never stored" list above.
- A new verb: one row of `VERBS` in `keel/cli.py` (its handler returns the payload, its
  `render` prints it, and its optional `aside` says one line about the payload on stderr,
  in both output forms, so stdout stays what a caller parses). The parser, the dispatch,
  `kb help` and the house brief all read that row. For a verb the deck runs, add its argv to
  `actions.ARGV_BUILDERS`.
