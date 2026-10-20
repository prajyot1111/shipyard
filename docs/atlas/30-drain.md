# The drain

The drain is a deterministic loop that starts a house for each startable
card and reconciles every live card against what the harness reports. It is about 200
lines and has no rule beyond the six steps below.

## The pass

Every `poll_seconds` (30):

1. **List.** `harness.agents_across(...)` asks `claude agents --json` under the config dir
   of every space and takes the union. A listing sees only the sessions of the config dir it
   runs under, so one listing is not enough.
2. **Carry.** For every card this drain owns with a pending `relay` (the user's held taps and
   `land`, below; one addressed to an older host name is carried here too, c-622), mark it `carried` and then do it:
   tell the house the relay's prompt (resume it if it exited), stop it, or start the card. A
   relay whose card has moved to another session since the tap is answered `superseded` and
   not acted on; a resume for a house that is working is HELD, left pending until its turn
   ends ("Relays", below). Reconcile leaves a card carried this pass alone: the listing it
   holds predates it. A kick carries relays at any moment too, even mid-pass ("The kick", below).
3. **Reconcile.** For every unarchived, non-tracking card this drain owns (in a space it
   serves) with a `session_id` at `building`, or at
   `planning` with no `plan_ref` yet (the house died before delivering its plan;
   `drain.house_stage` is that rule): if no
   agent row carries that session id, the house has exited. If this card has no `resume`
   event yet, resume it once and record `resume`. Otherwise block it with what it last
   said: the `last_assistant_message` of the newest Stop event, else `last_said` on the
   transcript the hooks recorded, else the last 40 lines of `claude logs`. Reconcile is not
   capped by the pools ("The pools", below), and the houses it resumed are counted into
   them, into the browser slot and into the memory gate before step 5 reads any of them.
   A card already blocked is passed over (it is the user's), and one whose space's login has
   expired is held for it instead of resumed ("A space whose login expired", below).
   The one automatic resume is the drain's own (`house.auto_resume_spent`, c-605 review):
   its `resume` event carries `automatic` (`kb session --resumed <p> --automatic` over
   HTTP), and a later start of any other kind (the user's Resume, a gate answer, a batch told) or
   the user's Retry gives the house its one again. Otherwise the user's Resume would spend it, and a house that
   exits after the user's Resume would be blocked at once.
   A house THE USER stopped is passed over too (`house.stopped_by_him`, c-605): the user's Stop tap
   writes its note with the `human-stop` mark (`kb note --mark human-stop`, by the deck, or
   by the drain carrying a relayed stop), and while that note is newer than the card's last
   `session` or `resume` event (or the user's Retry) the house waits for the user's Resume or Retry. Without
   the mark the drain reads the user's Stop as an exit and resumes the house seconds later (11 s, measured). A house
   that exited on its own (a rate limit, a crash) is resumed as before. A shipping card's
   review batch reads the same rule (`shipping.deliver`): it waits, kept, rather than
   resume a house the user stopped, and says so on the card once (`shipping.HELD_BATCH_NOTE`).
   The card carries it as `derived.held_by_stop` ([cards](10-cards-and-gates.md)).
   A house the user CLOSED WHILE IDLE is passed over here too (`house.closed_while_idle`, c-607):
   the user's Close idle house tap marks its note `closed-idle` (`kb note --mark closed-idle`), and
   freeing its memory was the point, so the drain does not put it back 30 s later. Unlike
   the user's Stop it does not wait for the user's Resume: the next review batch at shipping resumes it
   (`shipping.deliver` reads only `human-stop` as a hold), and so do the user's gate answer and
   Resume, each with `claude --resume`, its conversation continuing. The drain never closes
   a house itself; it only carries the user's relayed tap (below). The card carries it as
   `derived.closed_idle`.
   **A pass never puts a house on a card Bosun builds** (`derived.bosun`, c-647), whatever
   session it carries. Without this, a card carrying an exited house session from a start made by
   accident is resumed by the drain when Bosun moves it to building: the old house is resumed
   once, and builds and stages review on a branch of its own, or writes a
   plan. What the code does for such a card, each a decline and never a stop:
   - **This step**: reached exactly where a house's card would be resumed (after the voice
     hold, the drop-in hold, a listed session, a block, the user's Stop and Close idle), it is
     neither resumed nor blocked "exited twice", and the card says so in one note per
     session (`drain.leave_to_bosun`, `LEFT_NOTE`), where the user would look when a card of
     Bosun's shows a house session. An expired login does not hold it either.
   - **Step 4** (the quiet rule): `drain.reconcilable` is `house_stage` and not Bosun's, and
     `idle_stuck` reads it, so a listed quiet session there is neither resumed nor blocked,
     and nothing is said: it is still running.
   - **A login hold it already carries** is taken off once the login works, with a note and
     no resume (`loginhold.release`, "A space whose login expired").
   - **An expired voice hold** is cleared and no house is woken (`release_holds`, "A card
     voice is talking to").
   - **A start**: `views.startable` and `claimed_unstarted` already refuse it (c-645).
   - **A conflict at its landing** sends the card back to building for Bosun, with no house
     resumed (`landing.refused_here`; [cards and gates](10-cards-and-gates.md)).

   What still reaches a house on such a card is somebody's word, never a pass's own: the user's
   taps (Resume, a gate answer, Retry, a relay the drain carries for the user) and a rotation the user
   or Bosun asked for (`rotate.upkeep` finishes only a rotation that was asked). And an
   Approve outcome still ends the card's own idle house before it lands
   (`landing.finish_house`), as on any card.
4. **Put back a house that went quiet.** The session is still listed and still idle, but its
   turn ended with no `Stop`: the account's rate limit cut it off mid-turn. After
   `idle_resume_minutes` (10) of that, resume it once with a fixed prompt, with the wait
   doubling each time, and block it after three attempts ("A house the account's limit
   stopped", below). The log line says `stuck=N`. Before a resume is spent, and at once
   when the house's own last words name a lost login, the space's login is asked; an
   expired one holds the house instead (`login=N`).
   Just before it, a house the harness shows **paused on a permission prompt** is blocked
   with the commands auto mode denied (`denied=N`), and the drain's own such block is
   cleared once that session is busy again (`recovered=N`) ("A house auto mode paused on a
   permission prompt", below).
5. **Start.** Unless `drain_paused`, while the houses on this machine are under the pool
   cap, the browser slot has room for a browser card, and the memory gate is open (this
   machine's limits, below), take the first startable card in QUEUE order ("The queue",
   below), claim it for this host (`kb claim`; a card another drain claimed first is
   passed over), cut its worktree, write its settings and brief, start it, record its session, and stage it `planning`
   (attended) or `building` (autonomous). A claimed card still at `assigned` (the drain
   went away between the claim and the start) is started again, whatever host name its
   claim carries: on one machine an older name is this one (c-622). A
   card whose space's login was last found expired waits (one log line per space), and the
   other space's cards still start; `--card` on one is refused with the login's reason.
6. **Watch the shipping cards** (`drain.ship_upkeep`, `keel/shipping.py`, lane SHIP), before the starts: look at a shipping card's pull
   request when its cadence says so, and tell each house the review batch that is due, in
   its own session (a resume of an exited house takes a HOUSE slot and the memory gate;
   "Shipping: the pull request watcher", below). The log line says `ship_resumed=N`.
6a. **Tear down what a finished building spell left up** (`drain.teardown_upkeep`,
   `keel/teardown.py`, c-532), right after the
   watcher: a card that has left building ("A card's own containers, torn down", below).
   The log line says `containers torn down for <ids>`.
7. **Leave alone.** A card at `review`, or at `planning` with its plan gate open, is never
   touched, whatever its session is doing. A TRACKING card is never resumed, nudged or
   blocked either, and its idle session is stopped once (`drain.retire_tracking`, below).
   One whose slices are all done is closed to done, with a rollup of its slices written as
   its outcome (`state/cards/<id>/outcome.md`), unless it is blocked, held, or has an open
   ask, and one at review or done is taken back to tracking when a slice leaves done
   (`drain.close_tracking`, lane X, c-649,
   [cards and gates](10-cards-and-gates.md)); the log line says `closing=N` (closed) and
   `unclosed=N`.

The watcher (step 6) runs before the starts (step 5 in the list, which the code runs last)
so an exited shipping house resumed with its batch, which answers a reviewer, takes a free
house slot ahead of a new card. A shipping house holds a slot only while it works
(`drain.holds_slot`, c-600).

**The kick** (c-598, `keel/kick.py`). A thread of the drain's own (`kick.Listener`, c-608)
waits on its inbox, a unix datagram socket at `state/drain.sock`, for the drain's whole life,
while the loop itself only sleeps `poll_seconds` between passes (`drain.rest`). A datagram
there runs `drain.carry_pass` at once, even while a pass runs: `deploy.kicked` first (the user's
Deploy started, below, before any listing and in a `try` of its own, so its trouble is logged
as `deploy kick failed` and never changes what the carry reports), then one listing and
`carry_relays`, nothing else, logged as `kick:
carried=N` when it carried something. While a relay it tried is still held it carries again
every 2 s, five times (the listing says idle within a second of the Stop that kicked it),
and the full pass keeps its own 30 s clock. Until c-608 the inbox was read only between
passes, and a tap could wait out a 75 s pass (shipping polls of 19
cards, c-567) before it was carried. One process-wide lock
(`drain.CARRY_LOCK`) is held by every carry, the thread's (listing and carry both) and the
pass's own `carry_relays`, so the two never carry at once; at most once is still the
board's (`kb carried`) and the card lock's. What the thread carries while a pass runs, that
pass leaves alone from then on, as it does its own carried cards, since its listing
predates it (`drain.MIDPASS`, read through `drain.PassSkips`), and the pool slots it took
are counted before the pass starts anything. The thread marks each card there BEFORE it acts
on it (and unmarks one whose taps were all held), and reconcile's resume names the session
its snapshot holds (`house.resume(expect_session=)`): one the kick moved since is refused
(`house.SessionMoved`), so a house is never resumed twice. The tells both carries start are
joined under one lock in `keel/tellhouse.py`, each join waiting for those started before it. The thread never dies (whatever a round
raises goes to `failed_step` as `kick thread failed`, and it listens on), and the loop stops
it, letting a carry under way finish, when it exits, and before it execs itself for moved
code it waits for that carry however long it takes, so a carry is never cut after `kb carried`. Two things kick: `kb` right
after a verb that wrote a relay (`kb relay`, `kb approve` or `kb stage` with `--relay`),
which kicks this machine's drain through the socket (`kick.host`);
a house's Stop hook (`bin/keel-turn-end`) when its card has a relay pending for this
machine; and `kb` right after it recorded the user's Deploy (`kick.after_deploy`: `kb console
answer` of a deploy ask with A, which the user's tap and voice run, or `kb console deploy`),
which kicks this machine's drain before it prints, and puts what it found in the payload
(`kick`: `kicked`, or `no drain listening`), so the user's tap's toast says "the deploy starts now"
only when a drain heard it, and "waiting for the drain" otherwise (c-636). There is no signal and no pid, and nothing is stored: a kick nobody hears is lost,
and at most once is still the board's (`kb carried` before the act). A drain that cannot bind
the socket says so once and rests on its clock alone; one that finds ANOTHER drain listening
on it never takes it over (the kicks would silently split) and says so loudly in its log.
The tells a carry starts run side by side, four at most, and `carry_relays` waits for them
before the pass goes on, so a pass costs the slowest tell, not their sum. A tap reaches the
drain in about a second and the tell takes 7 to 13 s (a `claude -p` relay turn).

`keel drain --once` runs one pass; `--card <id>` starts that one card even while the drain
is paused, which is how a card is started by hand. `keel drain` (the role)
logs one line per pass to `state/logs/drain.log`, ending with how long the pass took
(`drain: houses=2 ... in 74.2s`, `drain.pass_line`, c-608, so a long pass shows), and never
lets a pass's exception out of the loop. The deck's header pill reads that log's newest `drain:` line.

**One pass runs at a time per install** (`keel/passlock.py`, c-734). Every pass, the loop's
and any `keel drain --once`, holds an `fcntl.flock` on `state/drain-pass.lock` for the whole
pass. An unscoped pass (the loop's, and the one a tell asks for, `pausewake.ask_pass`) does
not wait: one that finds the lock held does nothing and logs `drain: pass skipped: another
pass holds the pass lock`, and the loop simply runs its next pass on its next tick. A
card-scoped pass (`--card <id>`: Retry, create-and-start) is a tap waiting on its answer,
so it never skips silently: it waits for the lock up to
`passlock.WAIT_SECONDS` (90 s), then runs. The tap waits that long on top of its usual 180 s
for a keel command (`actions.CARD_PASS_SECONDS` is `passlock.WAIT_SECONDS` plus
`actions.SLOW_SECONDS`), so a pass that waited still has the whole budget a pass had before
the lock (r2.F2). When the wait runs
out it exits non-zero with "the drain pass for c-N did not run: another pass held the pass
lock for 90s; try again", which Retry reports as a failure. `--no-wait` makes a card-scoped
pass skip at once instead; Approve outcome's landing passes it (`actions.queue_landing`),
since it only nudges the drain and its tap returns now: the queued relay is the next
pass's. The lock is the kernel's, so a
pass that dies leaves nothing to clean up. A lock that cannot be used (the file cannot be
opened, or `flock` answers with an error other than "held", such as ENOLCK or ENOTSUP) lets
the pass run unguarded rather than stop the drain, and the log says so once a process. A
kick's carry (`drain.carry_pass`) is not a pass and is not held back by it.

Each pass also keeps `state/logs` bounded (`keel/logtrim.py`, `drain.log_upkeep`): a `*.log`
past 5 MB is copied whole to `<name>.1`, replacing the one before it, and cut back in place
to its newest 64 KB from a line boundary, with one line in `drain.log` naming what was cut.
It is cut in place because `keel.err.log`, `voice.log` and `talker.log` are held open by
launchd (or systemd's `append:`) for as long as the service runs, and a rename would leave
the service writing into the renamed file. Both open the file in append mode, so the next
write lands at the new end. The tail stays so the deck's pill never reads an empty log. A
log therefore costs at most about 10 MB.

Each pass also empties the board trash of what is past its time (`drain.board_trash_upkeep`,
`boardtrash.purge`, BD-1): a board deleted more than 30 days ago is removed and leaves
`<b-id>.purged` behind so its id is never minted again. It is the only place a board leaves
the trash for good; no request purges ([the board](45-board.md), "Deleting a board").

When `[backup] pull` is true each pass also offers the backup's pull
(`drain.backup_upkeep`, `backup.pull_upkeep`): when the last good pull is over 20 hours old,
none is running and none was started in the last hour, it starts `bin/keel-backup pull`
detached, under `caffeinate -i`, and logs `backup pull started`. A drain passes only while
the machine is awake, which is the point ([the backup](85-backup.md), "The second copy").

Where the config names a backup store and at least one set, each pass also watches the
hourly snapshot (`drain.snapshot_upkeep`, `backupdue.upkeep`, c-750), on the board's clock
and as the first step of the pass, before anything that can raise: a pass that fails
further down is still a machine awake with a backup owed. When the last success is over 75 minutes old, no run holds the tool's
lock and this is at least the second pass in a row inside five minutes (or a
poll and a half of `poll_seconds` plus a minute, where that is longer), it starts
`bin/keel-backup snapshot` detached, under `caffeinate -i`, and logs `backup snapshot
started`; a run that ended with no success is tried again ten minutes later, three starts
an hour at most. When no run has succeeded through two hours of the drain passing with one
owed (three hours after the last success, on a machine that never slept), and none is
running, it files one notice and logs `backup overdue` (a board
that will not take the card logs `backup overdue notice failed`, and the run is started
all the same). The service manager's hourly job is still the one that normally runs;
this is what catches it stopping ([the backup](85-backup.md), "When the hourly job stops").

Each pass also keeps the Logins list current ("Every credential: the Logins list", below):
after the board is closed it checks at most two due rows (`drain.logins_upkeep`, log
`logins: checked <id>`), and while the board is
open it raises or withdraws the login asks for this machine's rows
(`drain.login_asks_upkeep`).

## A card's own containers, torn down

A house proves its change in containers of its own (a test stack, previews), and those
belong to the building spell that started them. Once the card leaves building (the house
staged it to review, the user approved it to shipping or done, or it was archived) they only
hold the machine's container memory, which every house shares: a card at review can still
have its test stack and a preview up. So every pass, per card of a space this drain
serves whose adapter has the `ship` verb, whose house is here, that had a worktree cut
(`options.worktree` or `options.worktrees`), and that is not at building (or is archived):

1. **Is a spell unanswered?** The id of the card's newest event that moved it INTO
   building (a `stage` move, or the user's plan approval, which is an `approve` event),
   against `options.torn_down`. Equal, or no such event: nothing to do. A card whose
   `updated_at` has not moved since it was last found so is not read again by this
   process (`teardown.CHECKED`, a schedule and not a record: a restarted drain looks again).
2. **Must it wait?** It waits for a later pass while a busy row for it is in the harness
   listing, while the user holds it (a Drop in or a live voice hold: the user may be looking at its
   preview), and while another card still at building records the same worktree (two
   cards on one branch share it, so those containers are the building one's too).
3. **Tear down.** The adapter's `ship <id> down` stops and removes the card's OWN
   containers and keeps its worktree (what counts as its own is the adapter's:
   [the work adapter](60-work-adapter.md)). The spell is recorded in `options.torn_down`
   whatever the answer, so a failure is said once and not retried every pass, and one note
   on the card names what went, or why it could not; nothing up writes no note.

At most `teardown.PER_PASS` (4) cards a pass, and the whole step within
`teardown.BUDGET_SECONDS` (120): each card's adapter run is given what is left of it (at
most `teardown.DOWN_SECONDS`, also 120), and none starts with under
`teardown.MIN_SECONDS` (30) left. The adapter's own docker and preview calls are bounded
by far less.
The first pass after this shipped found every old card due once, and a pass must stay
short. The log line names only the cards that had something torn down. A send back is a
new building spell, torn down again when it ends. The reap at done runs the same sweep
before it removes the worktree.

## Shipping: the pull request watcher

A work card whose outcome the user approved sits at `shipping` while its pull request is open
([cards and gates](10-cards-and-gates.md), "Shipping"), and its build house LIVES ON beside
it (c-600): Approve ends nothing, no session is rotated, and the card never goes back to
building or review. The drain watches it
(`keel/shipping.py`). It watches ONLY shipping cards, and there is no "watch a PR" verb: a pull request of the user's that
Keel did not build reaches a card only through the shipping sync
(`bin/keel-shipping-sync`, [cards and gates](10-cards-and-gates.md)), onto the card it
belongs to. Every pass, per card of a space this drain serves, whose house is here, not
archived and not blocked:

1. **Look, when the cadence says** (`shipwatch.poll_due`, c-600): every 2 minutes while
   items wait (whatever the hour); every 3 while told items are not shipped yet or the pull
   request moved in the last hour (the approve and the user's Ship count); every 10 in work hours;
   hourly at night and at weekends. Work hours are `[keel] work_hours` and `work_days`
   (`"09:00-19:00"`, `"mon-fri"`, this machine's local time). The look is the adapter's
   `ship <id> poll`, three or four calls to the host, so a card with items waiting costs
   about 120 calls an hour, and only while they wait. It prints a SIGHT: the state (open,
   merged, declined), whether it is a draft, the comments by anyone but the author (bots,
   the tracker's link comment and resolved threads left out by the adapter), each reviewer's submitted review, the
   head commit's checks, and how far behind its base the branch is. No model is called.
   When this process last looked is kept in memory (`shipping.LAST_POLLED`), not on the
   card: it is a schedule, and a restarted drain looks once more, which is harmless.
2. **Fold it into the card's record** (`shipwatch.fold`, `options.shipping`), written only
   when something changed, so a quiet pull request puts no event on its card. The first
   look is a BASELINE: what was there by the record's `since` (when the user's Approve began,
   before its publish) is seen and not flagged, and anything later (a comment, a failed
   check ten seconds after Approve, a review whose `state_at`, the time its STATE was set,
   is later: never its `at`, which the work host moves whenever the reviewer takes part, so
   a sight without `state_at` has its reviews baselined; a comment from before but edited
   after, told as edited) is folded as new in the same look (c-604: the
   sandbox's were baselined away, and the chip said "1 comment, checks failed" with no
   rows). A thing the host gives no time for is baseline. After that a
   new comment joins the waiting batch (`pending`), a reviewer who asks for changes is an
   item that goes at once, an approval goes at once only when that reviewer also has
   comments waiting (and is otherwise good news for the chip), and a check that fails on
   the head is one item until a later look finds it passing again. A comment EDITED on the
   host (its `updated` time moved; `seen.edited` keeps each one's) joins the batch again
   under the same handle, marked `edited`, so the house judges what it says now (c-600
   review). `facts` is what the
   deck's chip says (comments, approvals, checks, behind, waiting, draft).
   **A card with a pull request in each of its repos** (SH-10, `options.prs`) is looked at
   as all of them in one sight (`prs`, one per pull request, the primary marked). The fold
   keeps what it saw per pull request (`seen` for the primary, `seen_other[repo]` for the
   rest; one that joins a watched card later is baselined alone), and the batch and its
   debounce are ONE across them. An item from a pull request other than the primary is
   handled `<repo>.<handle>` (`webapp-react.c21`), which is how the adapter sends its reply
   to the right pull request. **No comment is cut silently** (c-580): an item keeps a
   comment's text to `shipwatch.TEXT_MAX` (2,000), a longer one ending `[cut: full text in
   comments/<handle>.md]` (`CUT_MARK`), and every look writes each comment's whole text to
   `state/cards/<id>/comments/<handle>.md` (`shipwatch.whole_texts`, written by
   `shipping.keep_whole` only when it changed). `facts` sums the counts, takes the worst
   check and the furthest behind, and keeps each one's own in `facts.prs`.
3. **Merged**: the card goes to `done` only when EVERY one of its pull requests has merged,
   and the adapter's `ship <id> reap` takes its worktree away (keeping one with uncommitted
   changes, and saying so in a note); a worktree is never reaped for a card that is not
   done. A REVIEW card reaches done without a merge (its review posted, or closed), and the
   box test's review card kept its detached worktree for good, so the review fetcher's pass
   reaps a done review card (c-734, `keel/reviewreap.py`), never through a pack's generic
   reap (the work pack's finds a tree by the card's branch, which on a review card is the
   colleague's, so it could take a worktree of the user's, review r1.F3). It removes only the paths the pack RECORDED at the cut
   (`options.worktree`, `options.worktrees`, `options.review_worktrees`), and of those only
   the ones Keel's own layout cut (`spaces/<space>/<key>/trees/`, as the GitHub pack and a
   stranger's install have them), each with `git worktree remove`, never forced, and only
   one git lists as a linked worktree. A recorded tree anywhere else (a pack's own tree home,
   as the owner's work pack keeps its review trees) is reaped only through a pack that
   declares `review_reap` under `[capabilities]` ([packs](62-packs.md)), whose `ship <id>
   reap` removes that card's recorded paths with its own teardown; without it the tree is
   left alone, and its card gets one note for its round, "worktree not reaped by Keel", so it
   is not read again; an install whose pack does not declare it reaps nothing it
   did not before (the decision after review round 1). A pack that keeps a tree for a
   passing reason (a session live in it, sessions it cannot list, another card still using
   it) answers `later: true` beside its `removed` and `kept`, and a reap command that fails,
   times out or answers something malformed (no object, a `removed` that is not a list of
   paths, a `kept` entry that is not an object, r1.F5) is read the same way (c-743): the round gets NO `reaped`
   mark, so the card is asked again on a later pass, and why its tree waits is said on the
   card once, in a note carrying `reap_later: <round>` that ends "not cleaned up yet, asked
   again on a later pass". A pass runs at most `REAPS_MAX` pack reap commands, whatever each
   answers (removed, later or failed), since each may run to its timeout (r1.F3). A
   waiting card is asked after the ones not asked yet, and the waiting ones take turns,
   least recently asked first, so one whose command keeps failing cannot keep another from
   its turn (r1.F1). A waiting card Keel itself leaves (a hold, a listed house, a session
   in its tree) runs no command and no git, so it takes none of the pass's `REAPS_MAX`
   places and goes to the back like one that was asked (c-743 r2.F1). When each was last asked is kept in the drain process's memory
   (`reviewreap.ASKED`), never on the board: no write a pass, and a restart simply starts
   the rotation again. A pack
   that never sets the key is read exactly as before. A card none of whose recorded trees
   is left on disk gets its own plain note once, "no worktree left to reap"; a pack whose
   `pack.toml` cannot be read writes nothing, and the card is asked again next pass. A
   card whose session the harness still lists, idle or working, and a tree any listed
   session runs in (every space's config dir is read, as a pass reads them, r2.F3), are
   left until the harness no longer lists them, and a listing that fails reaps nothing
   (r1.F1). A card under a voice hold or a drop-in hold is left until the hold is gone
   (r2.F3). Its note carries `reaped: <round>`, so it is done once a
   round and a Re-review's new tree is reaped again (r1.F2). One query finds the
   candidates: done review cards of the space updated in the last `RECENT_DAYS` with no
   reap note for their round, `REAPS_MAX` a pass (r1.F9). A round that carries a
   `reap_later` note is exempt from the `RECENT_DAYS` cut (c-743 r1.F2): its note promised
   another ask, so its age never drops it; the pass's budget of pack commands is what
   keeps asking cheap. The waiting
   rounds are read by a query of their own (`reviewreap.WAITING`, c-743 r2.F2, r2.F3), from
   their notes through the `events_reap_later` index (`keel/board.py`), so the first query
   keeps its plain recency cut and a card past `RECENT_DAYS` that never waited costs
   nothing; and with a limit of their own (`WAITING_MAX`, 200, oldest note first), so the
   `CANDIDATES_MAX` recent cards never hide a waiting one from its turn. Two bounds, said
   plainly: a pass reads the 200 OLDEST waiting rounds of the space, so past 200 the newest
   ones are not asked until older ones clear; and that query reads every `reap_later` note
   on the board each pass, the ones of rounds since reaped included, a cost that grows
   with the notes this feature writes (one a waiting round, never one a pass). The two
   lists are joined, the cards not asked yet first. **Declined** (any one of them): one note, and the card STAYS at shipping with
   `state: declined` and nothing to ship (Ship is refused; Archive or Talk are the user's ways
   on); a pull request opened again is noted and watched as before.
4. **The worktrees' own facts** (`shipping.local_facts`, every pass, written only when they
   change, as `options.shipping.local`): BOTH sides of each worktree a pull request of the
   card is on (`shipping.ship_trees`: a worktree of a repo with no pull request is left
   out) against its pull request's branch as last fetched (`shipping.sides`: `git rev-list
   --left-right --count` against `origin/<its branch>`, `origin` being the space's `remote`
   setting (`config.remote_of`, c-665), and NEVER its upstream,
   `shipping.tracked`: a worktree cut from its base has its base as upstream, and behind
   the base is no reason to refuse a Ship; a branch the remote does not hold is nothing
   known; the adapter's poll fetches that branch on every look). `ahead` is the commits a fast-forward push would
   send, so it counts only a worktree that is not behind; `behind` is the commits that
   branch has and the worktree lacks; and a worktree that is both is DIVERGED (c-653,
   `diverged: {ahead, behind}`, git's own counts): its pull request's branch was rewritten
   outside Keel, and what is "ahead" there is the old history, not work to ship (a worktree
   left on old history once read "223 commits to ship"); or, when that branch is still at
   the head Keel last pushed, the worktree's branch was rebuilt here and is the history to
   publish, by the user's own paste of a push with a lease (r-55, c-723, `shipstep.published`). `unchecked`, whether the review
   stamp fails to cover HEAD of every worktree (the receipt
   `keel check` leads to, [houses](20-houses.md)); `conflicts`, whether HEAD conflicts with
   `origin/<base>` (`git merge-tree`, which touches nothing; a base this clone never
   fetched is no conflict known, asked first with `rev-parse --verify`, c-660). The deck's Ship says them.
   While a worktree is behind, the record carries THE sentence for it
   (`local.said`, `shipstep.said`: the counts and the by-hand way) and what the user types
   to bring each such worktree in line, or why Keel cannot say (`local.by_hand`,
   `keel/shipstep.py`, read-only; [cards and gates](10-cards-and-gates.md), "Review at
   shipping"):
   the pass that finds it writes that sentence as a note on the card, once per kind (when
   a worktree is first behind, and again when one that was behind diverges,
   `shipping.kind_of`), the Ship refusal of a diverged worktree is that sentence, and the
   deck draws it as given. The drain only reads: it never moves a worktree, and nothing
   in Keel does. The user's Ship writes `local` too: its own write drops `ahead` and
   `unchecked`, and `kb ship` then reads the worktrees and lays the facts over the record
   (c-660, [cards and gates](10-cards-and-gates.md), "Review at shipping"). So this step's
   write is refused when a Ship landed since the pass read the record: its own read of git
   may be from before that push. The check is made in the write's own transaction
   (`Board.keep_shipping(..., unless_moved=("shipped_at",))`), never before it, the pass
   goes on from the board's record, which is what comes back, and the next pass reads
   again. **Every write a step of this pass makes to
   `options.shipping` goes through `Board.keep_shipping`** (c-653 review): the step works on
   the copy it read at the start of the pass, so the record is re-read in the write's own
   transaction and only what the step changed is laid over it. The user's Ship's `posted`, a mark
   of `mark_reoffer`, a key another writer removed, and above all `heads` (the next
   Ship's lease), which the drain never writes at all, keep what the board holds. `facts`
   and `posted` are laid over the same way one level down (`Board.SHIPPING_BY_ENTRY`): a
   batch's take sets `facts.waiting` and forgets the re-told handles' entries of `posted`,
   and the draft the user's Ship marked ready and the replies it posted meanwhile stay. A batch
   that cannot reach its house is undone the same way, from the record as the take made it
   (`taken`, never the record as written, which holds other writers' keys by then) back to
   the pass's read, so only the keys the take changed go back. Every batch told
   while it lasts says so to the house in its prompt (`shipround.astray_text`): never
   rebase, reset, pull or merge to fix it, keep each commit small since the user replays it, and
   say in the verdict that the branch waits for the user. A base-merge item in that batch is
   told as held, never beside those words (`shipround.REBASE_HELD`).
5. **Tell the house when the batch is due** (`shipwatch.due`), which holds only the kinds
   whose automatic handling is on ("Automatic handling", below): comments and failed checks
   wait for 5 QUIET minutes, reset by each new one, and never more than 30 from the first;
   a submitted review asking for changes goes at once; a check that passes again before it
   goes is taken back. One batch takes every waiting item; what arrives while the house
   works on it waits for the next. A paused drain holds the batch. Each item is timed by
   the host's own time for it: a comment's, and a failed check's (`ci.at`, the status's
   update time) too since c-605, when its quiet timer started at the drain's first look
   instead; the first look stands in only when the host gives no time, and a host time
   ahead of the drain's clock counts as now.

**Automatic handling is two switches, both off by default** (c-655;
`keel/shipauto.py`). What the watcher finds is two kinds of work, and each goes to the house
by itself only where the user said so: review COMMENTS (a comment, and a submitted review asking
for changes; `ship_auto_comments`) and failing CHECKS (`ship_auto_checks`). Each is a
setting of the space (`[spaces.<name>]`, on the Settings page under "Tests and shipping")
and an option of the same name on the card, which wins (`kb set <id>
options.ship_auto_comments=true`, or the tap on the shipping card's pane; `null` hands the
card back to its space's). Only the user sets a card's (`board.HUMAN_ONLY_OPTIONS`, at create
too): a house that could would be deciding what wakes it.

**Off means collected, not told.** The look and the fold above are unchanged, so a merge, a
decline, the chip's facts and every comment's whole text are what they were. Then
`shipauto.settle` puts each waiting item where its kind says: the batch (`pending`) while
its kind is on, `options.shipping.untold` while it is off. An untold item is told to nobody
and never wakes, resumes or starts a house; it has no timer, so it does not bring the
2 minute cadence either. It is never lost: it is not baselined away (it was seen as new),
a check that passes again takes its own item back (`shipwatch.forget_untold`), the carry of
`bin/keel-shipping-upgrade` copies the record whole, the sync's fresh record keeps it
(`Board.ship_from_sync`), and the user's hand-over offers it (below). One kind on and one off is
a batch of the one kind, with the other kept. **Turned on later** (the card's option or the
space's setting), the untold items of that kind go back into the batch on the next look,
with their own times, so they are due on that pass; the look comes at the waiting cadence
(`shipauto.as_waiting`, 2 minutes at most) and not without one, because only a look can
say that a check kept untold has not passed since. **Turned off** with items of that kind
in the batch, they leave it at once, with no look (`shipping.keep_parked`). What the user handed
over in person is never parked (`shipauto.handed`): a filled re-offer goes whatever the
switches say.

**What waits untold is held to the code host on every successful look** (c-655 review,
`shipauto.reconcile`, before the settle): an untold comment the sight no longer shows
(deleted, or its thread resolved), a review that no longer asks for changes, and a check
that no longer fails are dropped, with one note on the card naming them
(`shipauto.GONE_NOTE`), so nothing stale is ever freed into a batch or counted. A review
that still asks carries the author the sight names, and that is the only urgency a freed
review brings. The same look keeps which comments and reviews asking for changes it showed
(`options.shipping.on_host`), and what the record saw once and never told, or told and
never judged, is counted, and accepted as something to ask for, only while it is among them
(`shipreoffer.never_told`). The deck's count and the verb's refusal read ONE function,
`shipreoffer.to_offer`, so a button never offers what a tap would refuse.

**This default is a change for every card that was at shipping before it** (deployed with
c-655): until then every new comment and failed check was told by itself. From the deploy,
a space that sets neither key tells nothing by itself; what was already waiting in a
card's batch moves to `untold` on the drain's first pass, and what arrives after is kept
there. Nothing is dropped, and each card says so in words. To keep the old behaviour, set
both keys to `true` under the space (the sandbox's config does, `demo/sandbox/keel.toml.in`).

The batch (`shipping.deliver`): the waiting items join `options.shipping.told` with their
batch number (`round` counts the batches), and the card's own house is given them through
`house.resume(..., tell=True)` ([houses](20-houses.md), "How a tap reaches a house"): an
IDLE listed house is told in its own session (a pointer to `state/cards/<id>/told/`, the
same session id and app link, no stop); an EXITED one is resumed once with the batch as its
prompt, or, when the harness no longer holds its conversation (a transcript past its
retention, c-654), started afresh with its brief, where the card's record is, and the batch
([houses](20-houses.md), "Resume and block": the note reads "started afresh", and a fresh
start that fails, or one Keel will not make because the board contradicts the harness,
puts the batch back and blocks the card like any batch that cannot reach
its house); a WORKING one is not told yet (the batch waits, and its Stop kicks this drain).
Every told batch keeps where its own turn starts on the board (`options.shipping.turn`:
its number and the newest event before the tell), which is how a later re-offer knows the
house is still on it.
EVERY batch, told or resumed, needs a free house slot and an open memory gate, exactly as a
start does, since each starts a turn (c-600 review: a burst across many shipping cards
would otherwise run more houses than the pool allows); with no room it waits in `pending`
for a later pass and is never dropped. The drain counts the houses woken (`ship_resumed`); a card that never had a house (one
the shipping sync found) gets one started with its brief (whose adapter half says the card
has shipped) and the batch. The words (`keel/shipround.py`) are the items, the adapter's
METHOD for judging review (`ship <id> method`, the colleague's method adapted, [the work
adapter](60-work-adapter.md)) and Keel's protocol: commit fixes without pushing, `keel
check`, one `kb verdict` per item, end the turn. It changes the card's `context.md` only
when its change alters how the thing works; anything else is in its verdict alone, which the user's
[review comments page](67-comments.md) shows (c-643). A batch that cannot reach the house goes
back to waiting and blocks the card with the reason (`mechanics`), and a blocked card is
not watched until the user unblocks it; a tell that fails on its own thread does the same
(`shipping.put_back`, handed to `tellhouse.deliver` as `on_error`), with its traceback in
`drain.log` and a note on the card, never silently. Each told batch is one note on the card ("batch 2 (3
items: nothing new for 5 minutes) told in its session").

**The user's own send-back** (c-663, `keel/shipsendback.py`, `shipping.keep_sent_back`). What the user
sent back on a shipping card (`kb ship <id> sendback`, `options.sendback`) needs no look
at the code host: every pass puts each ask into `pending` as an item of the user's own kind
(`his`, handle `his-<n>`, the user's words whole) and then takes exactly those asks off the card
by their handles (`Board.take_sendback`), so one the user sends while the pass runs is the next
pass's, and an ask whose item the record already holds is taken and never filled twice.
The item is ALWAYS told, whatever the two switches say, by one mechanism: its kind answers
to neither switch (`shipauto.ITEM_KINDS` does not name it, so `shipauto.settle` never
parks one). It is due on the pass that finds it (`shipwatch.due`, no quiet window), and
from there it is AN ORDINARY ITEM OF THE BATCH: it reaches the house the way any batch
does (a tell into an idle session, a resume of an exited one, a fresh house for a
conversation the harness no longer holds, c-654, a slot and the memory gate first), and it
waits while the house is in a turn, the ordinary way. The prompt gives the user's words exactly
as the user wrote them under a part of their own (`shipround.HIS`), with the rule that this is
the owner asking and not a reviewer: do it or say plainly why not, and nothing about it
is posted.

NO HAND-OVER MARK IS WRITTEN FOR IT (`options.shipping.reoffer` is the re-offer's alone,
and `shipsendback.fill` adds items to `pending` and nothing else), so nothing about a
send-back can stop a house or block a card: the close after a batch's turn and the unjudged
block both hang off that mark ("Idle houses at shipping and after a merge", below), and
without it the house is kept by the two-hour idle rule like any shipping house. A turn
that ends with the user's item unjudged leaves it as any unjudged told item is left: the pane's
"judging N", its row saying "told, not judged yet", and the user's hand-over able to offer it
again (`shipreoffer.his_unjudged`: the told item itself, since no code host holds it; the
deck's count is `derived.ship_handover.his`). If the user does hand it over, that batch is the user's
re-offer and the re-offer's own rules apply to it, unchanged; so they do when an item of
the user's happens to wait in the batch the user's re-offer fills. A card whose pull request was
declined is told nothing, and the verb refuses it.

A SEND-BACK WAITS WHILE THE HOUSE IS ON A RE-OFFERED BATCH, and only then. The user's ask is
NOT TAKEN (`shipping.keep_sent_back`) while the re-offer's mark is open
(`shipreoffer.is_reoffer`, read only) AND the harness, asked strictly, lists the card's
session with a process behind it (`shipidle.on_its_batch`, `housejobs.has_process`; a
listing that fails holds the ask for that pass): the house is on that batch, so the user's item
joins the next one. It stays on the card and the deck says what it waits for
(`shipsendback.held`, `HELD_HANDED`; the sentence never says the house IS on the batch,
which the board cannot know on a pass whose listing failed). The hold ends by itself in
two ways, and by the user's Resume for what is left:

- **That turn ends.** A waiting ask is itself a reason to settle the re-offer before
  anything is told ("A batch due behind a re-offer", below): on the first pass after the
  turn's end that has a slot, with the drain not paused, the listing answering and the
  house out of a turn, the re-offer is closed, ended as gone, or ended with a note, and
  the ask is taken on that same pass (a card that settlement blocked keeps the user's item in
  the batch until the user unblocks it, like any review).
- **The house is no longer running** (c-666 review): its session is listed no more, or is
  listed with no process behind it (the harness can go on listing a dead session). A
  house killed mid-turn left no `Stop` on the board, so that turn never read as ended and
  the user's ask waited for the user's Resume. A house that is not running is on nothing: the ask is
  taken, the user's item is due, and `deliver` resumes or starts the house the ordinary way (a
  house THE USER stopped waits for the user's Resume and says so, as any batch). That newer batch
  moves `round` past the old mark, which is then simply behind it.
- **The user's Resume**, for the one case left: a house that sits listed and alive with a turn
  that never ends on the board (a lost `Stop`). The sentence names it ("If the house sits
  idle and this still waits, Resume it"); the user's Resume tells it in place and records a
  later turn, so the re-offer is over by the board's order (`shipreoffer.batch_turn`
  OVER, `reoffer.done_at` written by the idle step) and the next pass takes the ask.

Once taken, the user's item is told as any batch is. A house open in the user's terminal is told
nothing by anyone (`house.InTerminal`: a resume there would start a second copy, and the user's
Resume tap is refused and records nothing), so a batch due for one is taken, refused, put
back, and SAID ON THE CARD once, until that house is next resumed or told (`shipping.IN_TERMINAL_NOTE`, the
same mechanism as the note for a house the user stopped): "it is open in your terminal: they
are told once you quit it there". That wait is the batch's own, not the re-offer's.
What the deck says of a waiting send-back names every true reason it is not on its way
(`shipsendback.held`): the pull request declined, the card archived or blocked, the house
stopped by the user (the batch waits for the user's Resume, `house.stopped_by_him`), the drain paused,
or this hold.

**The hand-over is the re-offer, as a tap** (c-655). The shipping card's button (`hand-over`,
"Hand 3 comments and the failing check to the house"; `hand-base`, "Bring the branch up to
its base") is the deck's `ship.handover`, which runs `kb ship <id> reoffer [--rebase]` as the user
(`actions.act_hand_over`), so everything below holds for it, refusals included. It works
with the switches on or off: on, it is for the backlog (what the baseline hid, what was
told and never judged). The fill also takes a check FAILING ON THAT LOOK that was kept
untold, or was told and never judged (`shipreoffer.check_item`; one the look shows passing
is neither offered nor counted, `shipreoffer.failing_checks` over the record's `facts`),
and clears `untold`, also when it finds nothing to offer: what is not in the batch by then
is gone from the code host. An untold item under a handle the house was told before (a comment
edited since, a check that failed again) is offered as new, never dropped as "judged
meanwhile".

**A re-offer** (c-651, `keel/shipreoffer.py`). The baseline (step 2) takes what was there
when the card entered shipping as seen, so review written before then was never told: c-239
had nine reviewer comments and was told none, and many such branches conflict with their
base. `kb ship <id> reoffer [--rebase]`, the user's alone, ASKS for them:
`Board.reoffer` writes `options.reoffer` (who, when, whether a rebase was asked), its own
option so the drain's write of `options.shipping` in the same pass cannot lose it, with a
note. It is refused off shipping, on a blocked or archived card, while an ask waits, on a
declined pull request, and when the record shows nothing to offer (everything seen was
judged or posted, or is in a batch the house is still on, below) and the branch is neither behind nor in conflict (unless `--rebase`); a move off shipping clears it, and so do a block
and an archive, each with a note (`Board._drop_reoffer`). The drain answers
it on its next pass: it looks at once (whatever the cadence),
folds the look as always, then puts in `pending` every comment of that look and every
review asking for changes that was never told, or was told and has no verdict since
(`shipreplies.unjudged`, c-654), never posted and is not already waiting, as
the watcher's own items (repo-prefixed handles for a pull request other than the primary).
Told is not judged: c-151's house was told four comments and ended its turn with a verdict
on none, and the user's next re-offer skipped them as "told" and offered a rebase instead. An item
with a verdict since it was told is never offered again; one told again takes the place of
its old row (`shipwatch.take_batch`) with a new `told_at`, so its row starts afresh
(`shipreplies.since`), and an earlier `rebase` item left unjudged asks for the merge again.

**A batch due behind a re-offer** (c-666, `shipidle.before_batch`). The watcher runs
before the idle step in a pass. So a batch that came due on the pass after a re-offered
batch's turn ended (a reviewer's comment whose quiet window was over, a review asking for
changes, a failing check, the user's own send-back) was told first, `round` moved past the
re-offer's mark, and the idle step no longer saw a re-offer: no close, no count of what
that turn left unjudged, no block, in `next` from c-654 until c-666. Now, where a batch
WOULD be told (something is due or the user sent something back; the card is not blocked,
declined or paused; there is a slot) and the record holds an open re-offer whose own turn
has ended or whose session has (`shipreoffer.turn_done`), the watcher SETTLES THAT
RE-OFFER FIRST, in that pass, for that one card, with the idle step's own function
(`shipidle.settle_reoffered`, what `close_reoffered` is made of) on a STRICT listing,
under the card's lock as any close:

- **Settled as ever**: the house is idle and is closed, or is gone (its session ended, or
  is listed no more). The bookkeeping is the idle step's, unchanged: the close, the count,
  the note, and the unjudged block for the user ("Idle houses at shipping and after a merge",
  below). A card that block lands on is told nothing until the user unblocks it. A house closed
  on this pass is told nothing on it, and the batch resumes it on the next: `claude stop`
  returns before the listing lets the session go, and a tell decides from that listing.
  A house that was gone is resumed with the batch on this pass.
- **The strict listing failed**: nothing is settled and nothing is told to that card on
  that pass (the plain listing answers a failure with an empty one, which must never read
  as "its session is gone"). THIS IS THE ONE WAIT, and it lasts exactly as long as the
  listing fails.
- **The close is refused**, and what follows is decided by the KIND of the refusal
  (`idleclose.NotIdle.kind`, which `idleclose.refusal` gives beside the sentence the user's tap
  reads), never by its words:
  - **A background job of the house's own, or a session open in the user's terminal**: the
    re-offer is over (`reoffer.done_at`, laid over the board's mark by
    `Board.mark_reoffer`), and when items of it have no verdict yet ONE note states the
    fact (`shipidle.NOT_CLOSED_FACTS`: "a background job of its own is still running", "it
    is open in your terminal"; never the tap advice of the close's own sentence), names
    them, and says the house may still be judging them. NO STOP: nothing automatic ends a
    house that is not idle, and none is stopped after a newer batch was told to it. NO
    BLOCK: a house that ends a turn to wait on a job of its own goes on judging
    afterwards, so "left unjudged" at that bare `Stop` may be a false alarm, and a block
    would hold every later review until the user lifted it. The note promises no tell and
    invites no re-offer, for the same reason; nothing is written on the mark that only
    the note needs. The batch is then taken as usual, and that house is an ordinary
    shipping house from there: kept by the two-hour rule, its unjudged items the pane's
    "judging N" and the user's hand-over's to offer again.
  - **A listed row with NO process** (seen on the watcher's own strict listing, or by the
    close a moment later): that house is not running, so nothing can still be judging in
    it. It is settled as GONE, with the gone case's count, mark and unjudged block, in the
    words "its session is no longer running" (`shipidle.NOT_RUNNING`). This is safe with
    no hook of its own: the settlement is reached only once the batch's `Stop` or
    `SessionEnd` is on the board, so the turn did end, and the idle step's own "listed no
    more" case rests on exactly that. It is written under the card's lock
    (`shipidle.settle_gone`, as is the same settlement of a session listed no more): the user's
    Resume of that house holds that lock while it starts the session and records its turn
    only after, so the lock is tried and never waited for (busy, the card waits this
    pass), and under it the board is read again: with a turn on record by then the
    re-offer reads over, and nothing of "gone" is written; nor is it with a message being
    sent or a tap of the user's on its way.
  - **The stop itself failed** (`claude stop` answered an error): nothing is settled and
    nothing is told to that card on that pass, like a failed listing; the next pass tries
    again, as the idle step always did. A stop that keeps failing holds the review behind
    it, so the card says it ONCE, until the house is next resumed or told
    (`shipidle.STOP_FAILED_NOTE`, through `shipping.note_held_batch`: Shipyard could not stop
    it and keeps trying, with the harness's own line; the re-offered batch is settled once
    the stop goes through; and the waiting items are told after that, or after the user's unblock
    if that batch left items unjudged, since the settlement then blocks the card). No
    timer and no counter: each pass tries again from nothing.
  - **The house is working** (it started a turn between the watcher's listing and the
    close's): nothing is written, and `deliver`'s own wait holds the batch until that
    turn ends, when the re-offer is settled as ever.
  - **Anything else** (a message or a tap of the user's on its way to the house, a hold of the user's, a
    card that left shipping meanwhile): nothing is written and nothing is held. The batch
    goes on to `deliver`, which does with it what it does on a card with no re-offer; if
    it is told, `round` moves past the mark and that re-offer is left behind it, which is
    what `next` did for every batch before c-666. Each of these is a turn of the user's starting
    or about to, which ends the re-offer by the board's order anyway.

Each wait above (the listing, the stop, the card's lock, a house closed on this pass, a
card just blocked, a card in the skip set) is one line in `drain.log` with its reason, as `deliver`'s are.

NOTHING IS CARRIED FROM ONE PASS TO THE NEXT: no field says "this waited", so nothing can
go stale, and each pass decides from the board and a fresh listing (a house that had a
job when its turn ended and is idle by the time a batch comes due is closed, and blocked
for what it left, exactly as with nothing due). A card in the pass's skip set (the drain
already carried a tap to its house, released a hold on it, or found the user dropped into it
on this pass; `drain.ship_upkeep` hands the watcher the same set the idle step gets) is
told nothing and settled by nobody on that pass, and is the next pass's. That set cannot
starve a card: each entry is something the drain DID in that pass (one tap carried, one
hold released, one login put back), never a standing state, and a tap, a voice hold and
a Drop in each start a turn or a hold on the board, after which the re-offer is over by
the board's order and this path is not entered at all. The idle step later in the same
pass finds the mark settled and does nothing more; a house the watcher CLOSED is named
back to the drain (`shipping.upkeep`'s `closed`) and joins that step's skip set for the
pass, because the pass's listing was taken before the stop and still shows the session,
and the two-hour close would otherwise stop and note it a second time.

So behind a re-offer whose turn has ended, a reviewer's batch or a send-back of the user's waits
for nothing but what any batch waits for (a slot, the drain running, the house out of a
turn), plus the listing answering, and at most one pass more when the house was closed
or the pass had already acted on the card. A re-offer whose turn has NOT ended is left to
`shipping.deliver`'s own rule, unchanged: the batch waits while the harness lists the
house in a turn, and is told as soon as it does not (a house killed mid-turn with no
`Stop` is resumed with it at once, and that re-offer's mark is then simply behind the
newer batch, with what it left showing as the pane's "judging N"). A card with no open
re-offer never enters this path.

**What the house is still on is not offered** (c-654 review, `shipreoffer.held`): asked
mid-turn, the items it was judging were queued again, told again once its turn ended, and
the verdicts it had just written dropped by their rows' new `told_at`. So the batch told
last is left out while its own turn has not ended by the board's order of events
(`options.shipping.turn`, `shipreoffer.batch_turn`), and, at the drain's fill, while the
harness lists the house in a turn. An ask with nothing else to offer is refused saying the
house is still on that batch; a fill that leaves them out says so in its note. And an
item offered again is checked once more when its batch is finally told
(`shipping.still_unjudged`): the batch can wait for a slot, and one the house judged
meanwhile is dropped with a note, never told again.
The sight already leaves out the author's own comments and every bot's, the tracker's link
comment among them ([the work adapter](60-work-adapter.md)), so what is offered is the human
reviewers'. A look that fails keeps the ask (`failed`, the reason) for the next look at the
normal cadence, and the third failed look clears it with a note naming the failure
(`shipping.look_failed`); each such write re-reads the ask in its own transaction and lands
only while the card is still at shipping with that same ask (`Board.keep_reoffer`), so a
block or archive meanwhile is never undone. With `--rebase`, or when nothing else is left but the branch is
behind or conflicts (`local.conflicts`, `facts.behind`), one `rebase` item asks the house to
bring its branch up to its base by MERGING the base in (`git merge origin/<base>`), resolve
the conflicts, run its checks and commit. The base is the card's real one, never a guess
(`shipping.base_of`): the user's `options.base`, else the branch the pull request itself merges
into, which the sight names (`base`) and the fold keeps as the record's `base`; the
conflict check (`local.conflicts`) reads the same. With neither, `--rebase` is refused with
a note (`shipreoffer.NO_BASE_NOTE`) and the rest of the re-offer still goes; a plain
re-offer with nothing else to offer on a branch behind a base nothing names writes no rebase
item and says so (`shipreoffer.BEHIND_NO_BASE`: set `options.base` and ask again), never
that the branch is up to date. Its words forbid `git rebase`, rewriting a pushed
commit and any force push (`shipround.REBASE`): the user's Ship's push is a plain fast-forward,
leased or not, so the merge goes with it and a rewritten history never has to. It is
answered by the merge commit (`--verdict valid --commit <sha>`) or, when the house cannot
finish it, `--verdict deferred --why`, never with a reply (`shipreplies.rebase_verdict`), so
nothing is posted for it. The batch is due at once (`urgent`), the ask is cleared with a
note naming the items (or why there were none), and the batch that carries them is marked
`options.shipping.reoffer` with its `batch`, `told_at` and `after` (the newest event on the
card before the tell). Its words end by saying the session is stopped when this turn ends.
Once the house's turn on that batch ends, the drain closes the house as idle ("Idle houses
at shipping and after a merge", below).

Nothing here pushes, posts or merges. At shipping the house's push, the adapter's `pr` and
`publish` are refused three ways: by the adapter itself (the work pack's
`fence.refuse_unless_shipping_tap`: `pr` never runs at shipping, and `publish` only while the
user's Ship's `options.publishing` marker stands, which only `Board.mark_publishing` writes,
under the user's tap, for the deck's Ship and `kb ship` alike; a pack on the kit goes further,
`pulls.refuse_unless_shipping_tap` with `pulls.in_tap`: its `publish` runs at every stage only
with the nonce of the user's tap, Approve outcome or Ship, which `cli.publishing_tap` marks on
the card and hands the verb, and only while that marker is fresh, c-738), by the settings file every resume and every tell rewrites (the adapter's
`deny` for the stage it is at, and the guard hook with the card's id), and by the house
guard, reading the stage live (a `git push` in any spelling it sees, git's argv spelled out
for a subprocess, and the adapter's `codehost` module). The user's Ship pushes and posts ([cards
and gates](10-cards-and-gates.md), "Review at shipping").

**Teardown at shipping.** The house may bring its test stack up again to prove a fix, so the
teardown step (below) treats each turn at shipping as a spell: the newest Stop after the
card moved to shipping is answered with the adapter's `ship <id> down`, once per Stop
(`teardown.spell`, c-600 review).

**Ending a house after the merge** is decided and built: "Idle houses at shipping and after
a merge (a-72)", below.

## Stacked cards (c-718)

A card the owner stacked on the card it waits for is cut from that card's branch and its
change aims there ([cards and gates](10-cards-and-gates.md), "Stacked or independent").
Each pass, after the watcher (so a parent it found merged this pass is done already),
`drain.stack_upkeep` runs `keel/stackwatch.py` over every stacked card of a space it serves
that is not done or archived, reading what the parent's own card says (`derived.stack`):

- **The parent landed is read first** (r1.F5): a parent that is done counts as landed even
  when it was archived after, so the steps below run and nothing is blocked.
- **The parent was dropped** (archived and not done, or gone): the card is blocked ONCE with one
  sentence, `<parent>, the card this one is stacked on, was dropped, so the branch it is cut
  from will not merge`, and the two ways on (make it independent, or archive it). A card
  already blocked is left, and one the owner unblocked is not blocked again for that parent
  (the block's data carries `stack`).
- **The parent landed** (done), for a card that started (a session, or a change recorded):
  1. **Its change is aimed at the base** by the pack's `ship <id> restack`, once, for a card
     that records a change ([the work adapter](60-work-adapter.md)). The code host is not
     relied on to do it. The answer is one note (`<parent> merged into <base>: pull request
     #50 in cloud now aims at <base>`); the base is the one the parent merged into
     (`derived.stack.base`, r1.F12). A failure is logged, noted once, and tried again after
     `RESTACK_WAIT` (120 s), doubling each time; after `RESTACK_TRIES` (3) failures in a row
     the card is blocked once with the reason and what to do (r1.F11), and the owner's
     unblock starts the count again. Each failure is a mark on the card carrying `n` and `at`
     (r2.F7, `stackwatch.failures`), read by the board's clock for the count and the next
     try, so a drain that restarts keeps both. A pull request the restack left because it is
     not open (the host declined or closed it when the parent's branch went, the pack's
     `kept` with its `state`) blocks the card once (r2.F6, `stackwatch.CLOSED`: reopen it, or
     open a new one against the base) and no rebase is told until the owner unblocks it.
  2. **Its house is told**, by a message into its own session, that the parent merged, that
     its change now aims at the base, and how to move the branch onto the base with only its
     own commits: ONE command per repo of the card, each with that repo's pushed head of
     the parent (r1.F3): the base fetched by its FULL refspec (r2.F3, as `shipstep.chain`
     does, so a clone with a narrowed refspec never rebases onto a stale ref); the parent's
     head fetched when the clone lacks it, by the parent's branch and else by its sha (r2.F4);
     `fork=$(git merge-base HEAD <head>) && test -n "$fork" && git rebase --onto
     <remote>/<base> "$fork" && git push --force-with-lease --force-if-includes <remote> HEAD`.
     A head nobody has any more stops the command before the rebase and the push, and the
     words say what to do then (find the fork point with `git log` and use it). A repo with no
     pushed head gets the words and no command. A repo the parent never named gets no line
     at all (c-772): the card was cut from its own base there, so nothing of the parent's is
     under it. The push is the pipeline's own after a rebase. That command is right for a squash merge
     and for a merge commit alike (after a merge commit it equals a plain rebase), so
     nothing has to know which the team uses. A card at SHIPPING is told to leave its branch
     alone, since only the owner's Ship pushes there, and the commands are the owner's, said
     where every out-of-step branch is said (below).
- **The parent's branch moved** (the owner's Ship pushed a review fix, the parent's
  `options.shipping.heads`) and the card's worktree does not hold the new head (`git
  merge-base --is-ancestor`, read only; a read that fails tells nothing): its house is told
  once per head to merge the parent's branch in, never to rebase what it pushed.

**Who is told, and who never is.** A tell goes only into a house the harness lists IDLE with
a process behind it, through `tellhouse.deliver(..., exited=REFUSE)` (r1.F4): the house is
listed again under its lock at the tell, and one that exited since the pass's snapshot is
refused (`tellhouse.NotRunning`), as is a relay that fails, never resumed in its place. The
send runs in line, so the step's once-only mark is written only after it went; a refused
tell is tried on a later pass. Each tell takes a house slot and the memory gate like any
turn, counted once against the pass's room (r1.F10). A WORKING house waits for a later pass. An exited house at planning or building
waits too, because the drain puts it back. Any other house that is not running (an exited
one at review or shipping) is NOT woken: the card gets the words as a note instead. Nothing
here stops, resumes or starts a session. Every once-only step is marked by the note or block
it writes (its data carries `stack`: the parent, the event, a head), so there is no second
record.

**A squash merge at shipping, by hand** (`shipstep.restack`, `shipping.local_facts`). The
out-of-step machinery says it, read-only, beside a branch behind or rewritten: for a stacked
card whose parent landed, each worktree of a pull request whose fork point from the parent's
branch (`merge-base HEAD <the parent's head>`) is not in `<remote>/<base>` as last fetched
is one entry, `local.restack` true and the one sentence (`shipstep.restack_said`: the parent
was squash-merged, so the branch still carries its commits as they were). Its command is
one chain like the others: into the worktree, HEAD still where it was worked out, the base
fetched by its full refspec, a backup branch, `git rebase --onto <remote>/<base> <the fork
point>`, and `git push --force-with-lease=refs/heads/<branch>:<the remote's head as last
fetched> <remote> HEAD:refs/heads/<branch>`, so a push someone made since is refused, never
overwritten. A merge in the card's own commits, or git that could not be read, gives no
command and says why; a merge that only brought the parent's branch in (each of its other
parents is in the parent's history, as the "moved" tell asks for) is not the card's own and
is dropped by the replay, which is what keeps the squashed commits out (r1.F6,
`shipstep.own_merges`). A parent head this clone does not hold gives no command and no
"squash-merged" sentence, since that cannot be told yet: the sentence says the parent merged
and gives the fetch that brings the head in (r2.F4, `shipstep.PARENT_UNREAD`). The read stays
read-only and fetches nothing itself, as every out-of-step read does (c-653). The note is said once per change of kind (`restack`, `kind_of`), and
the deck draws it as it draws a branch behind: the sentence, the commands to copy, and Ship
still offered. A base the record still names as the parent's branch (the watcher's next
look has not yet seen the change aimed at the base) waits for that look.

**What is not done**: Keel never runs the rebase or the push itself. A tool that rewrites a
branch for the owner is its own card (c-659), and c-653 decided Keel moves no branch here.

## Reviews: the fetcher (lane RC)

A pull request that needs the user's review is a REVIEW CARD, and the drain files it (`keel/reviewcards.py`, `drain.review_upkeep`, run every pass
after the shipping step and before the starts). Per space whose adapter has the `review`
verb, on the watcher's cadence (`shipwatch.poll_every`: 15 minutes in work hours, hourly
outside, and at once when this process has not looked yet; `reviewcards.LAST_SCANNED`,
in memory, as `shipping.LAST_POLLED` is):

1. **Scan.** The adapter's `review scan` says which open pull requests need the user, in the
   engine's words (a key `<repo>:<number>`, title, author, when it was raised, head,
   branches, url, description).
2. **File.** ONE card per key, ever: every review card of the space is looked at, archived
   and done included, so a pass never files a second. The card is autonomous, kind
   `review`, in the review pool (`options.slot = review`), on the review model, titled "Review: <title>", its brief the pull
   request's own words, its `options.review_pr` what the Reviews page sorts and filters by
   (author, raised, updated, url, head, and `activity` with the space's
   `review_backlog_days`). It waits in the INBOX until the user's Review tap moves it to assigned;
   with auto review on it is filed at assigned and starts like any card. A row the pack marks
   `fork: true` (c-730 r1.F1: code from outside the team, which on a public host a stranger can
   send the user's way) is filed in the inbox whatever auto review says, with
   `options.review_fork` and a line in its brief saying it comes from a fork, and its note says
   it waits for the Review tap (`reviewcards.FORK_OPTION`); its house reads that code and never
   runs it ([houses](20-houses.md), r2.F3). Every pull request
   that needs the user is filed whatever its age: an old quiet one sits in the BACKLOG ([cards and
   gates](10-cards-and-gates.md), "backlog").
   Each pass also refreshes a filed card's `review_pr` (written only when it changed), which
   is what moves a card into and out of the backlog. A card the user DISMISSED (Dismiss review on
   the deck, which archives it) is left as it was while its pull request is still, and comes
   back, the same card with a note, when the pull request is listed with activity AFTER the
   dismissal: its `activity` stamp (the host's update stamp, or a new head this fetcher saw)
   later than the newest event that archived it (`reviewcards.revive`, RC-8).
3. **Tend.** An inbox card whose pull request left the list is polled (`review <id> poll`):
   closed or merged, it becomes a NOTICE (`options.notice_key`), which Attention shows with
   Dismiss; one the user approved elsewhere is left alone. A POSTED card (done, with
   `options.review_posted`) whose pull request has a new head gets `options.review_new`
   and one note, "new commits since your review", which the user's Re-review answers; one whose
   pull request closed gets `options.review_closed` and is never looked at again.

**A story's pull requests are ONE card** (lane GRP, GR-1, `keel/reviewfeature.py`). The
adapter names each row's story (`group`, its rule on the branch name). Two or more rows of
one story that need the user become ONE feature card keyed `feature:<story>`: titled "Review:
<story> · <story title>" (the adapter's `review story`, else the first pull request's
title), `repo` the members' repos, `options.review_members` one record per pull request
(repo, pr, head, branch, url, author, raised, and its label `<repo>#<number>`), and
`options.review_pr` the facts over all of them. A row with no story, or alone in its story,
is a single card as before (it carries `options.review_group`). The members' heads together
are the card's head (`reviewfeature.composite_head`), so a push on any member, a member
joining or one leaving is "new commits since your review" on a posted card, and each join or
leave is noted. A feature card is kept down to one member (no single card is then filed),
and one whose members are all off the list is polled member by member (`review <id> poll`
answers `{members}`), closed only when every one is. A story whose every member already has
a single card posted at its current head files no feature card: there is nothing new.

**Folding** (GR-4): when a feature card forms, or a member joins, that member's own single
card is archived with a note pointing at the feature card (`options.review_folded`) when
nobody is deciding it: at the inbox (held included), or posted, whose ledger then joins the
feature's (`options.review_carried`, each line naming its member) so the feature review
never raises again what the user answered there. One queued, being reviewed, or at the user's gate is
NEVER folded: it and the feature card each get a note, the user decides, and the feature card
waits at the inbox even with auto review on.
A single card archived while a feature card covers its pull request (folded, or one the user
dismissed for it, c-480) stays archived when that pull request moves: the
feature card reviews the new push, and RC-8's revive is for a pull request nothing else
reviews.

**Twins** (2026-09-25, reshaped by c-559 on 2026-09-27, `keel/review/twins.py`, decision
TW-3): a story's change raised on two bases of one repo is reviewed ONCE. Who is a twin is the
ADAPTER's to say: a scan row may carry `twin_of`, the label of the member it follows (the work
adapter's rule, [the work adapter](60-work-adapter.md)), and it rides on the member in
`options.review_members`. The twin stays a member: it is on the card, and its head is in the
composite head, so a push on it is still "new commits since your review". The house brief
passes it to `keel-review prep` as `--twin <twin> <member it follows>`; prep leaves its diff
out, names it in the followed member's header and records it in `review-twins.json` in the
card directory (what this round reviewed). The lint (C32) refuses a finding or a verdict on a
twin, naming the member to use, and wants the orientation to name each twin with the member
it follows in one block. The user's Approve gives the twin no inline comment, one pointer comment to
the followed member's pull request in place of the summary, and the followed member's verdict,
so the two leave the user's queue together.

**The wait** (GR-3, `keel/reviewwait.py`, the old scanner's hold). A new card whose story
has a BRANCH, but no open pull request, in another reviewed repo (`review branches <story>
<member repo>...`, one read-only call; the scan's `open_groups` says which repos have an open
pull request of the story, the user's or not) is filed HELD: at the inbox with
`options.review_wait` = {story, sibling_repo, since, hours}, never auto assigned, and
`derived.review` says `held` (`derived.review_wait` adds `hours_left`). Every poll, per held
card, at most one call: the window (`[spaces.<name>] review_sibling_hours`, 48) run out
releases it ("reviewed alone: the <repo> side was not raised in 48h"); the other side raised
but not the user's releases it at once; the branch gone releases it; otherwise nothing is written.
The sibling raised and needing the user makes the story a feature card, which folds the held one.
The user's "Review now anyway" (the deck's `set` of `review_wait` to null and `review_alone` true)
ends the wait at once. A released card is at Detected (the inbox), or assigned with auto
review on.

**The two settings** are the space's own, not the adapter's (lane RETIRE, RT-2,
`keel/reviewsettings.py`): auto review (`review_auto` under `[spaces.work]` in the install's `config.toml`,
off) and the review model (`review_model`, opus; sonnet for a space that names none). The
deck's gear on the Reviews page sets a live override in `state/review-settings.json`,
never in the config file (a tracked config, as a checkout once kept, stopped the checkout following main when dirty), and the fetcher reads the override first on every filing.

A review card's house then runs in the review pool like any card, through the login hold
and the memory gate. Nothing here starts a house, posts or pushes.

## Claims and relays

The drain serves every space (`Config.served_spaces`), and its start is a claim:

- **A start is claimed.** The claim that commits first wins (`kb claim`), and the claim
  stays on the card as the record of which host runs its house. A second drain on the same
  board (a hand-run `keel drain --once`, say) passes over a card the first claimed.
- **A drain reconciles the cards of the spaces it serves**, whatever host name their claim
  carries: Keel runs on one machine, so a claim under an older name is this machine's
  (c-622).
- **Which card can start here** is `keel/where.py`'s one question (below).

**Relays: taps carried by the drain.** A tap that cannot act at once (a resume for a
working house, Approve outcome's landing, a stop, a start) is written to the board as a
`relay` event, and the drain addressed by `--to` carries it. They are `relay` events (`kb relay <id> resume|stop|close-idle|start|land|rotate|finished --to
<host>`, the human's alone; `close-idle` is the user's Close idle house (c-607), carried by
`drain.carry_close_idle`, which checks the house is still idle on its own listing, under the card's lock (`idleclose.close_here`, never while a tell is in flight) (no turn,
no job of its own running, not in a terminal, no voice hold, `idleclose.not_idle`) and
otherwise leaves it running with a note, and marks its note `closed-idle`; `finished` ends the house of a card whose outcome the user just approved and which is now done (a work card at shipping keeps its house, c-600), and only a house the harness does not list as working: a working one is left running with a note (`drain.carry_finished`, lane L); `rotate` asks for a rotation, [houses](20-houses.md); `land` is Approve outcome carried to the drain that holds the
worktree, [cards and gates](10-cards-and-gates.md), "the landing queue"), and pending is derived: a `relay` no `carried` event names, listed oldest
first on every card read as `derived.relays`. There is no queue to agree with the board.
A gate move and its resume are one write (`kb approve <id> plan --relay <prompt> --to
<host>`, `kb stage <id> building --relay ...`): were they two, this drain could pass
between them, see the card at building with no house, and resume it with the generic
prompt instead of the approval's. Carrying is at most once: `kb carried <id> <relay>` (a
drain's alone) comes BEFORE the act, as the claim comes before a start, so a drain that
dies mid-way never acts twice. A relay names the session it
was tapped for, so a Stop tapped at night never stops the house that replaced it by
morning. A `start` (Retry) starts the card even on a paused drain, as `--card` does, and
stays pending while its pool is full or the memory gate is shut. A failed resume blocks the
card with the reason; a failed stop is a note. The log line counts them as `carried=N`, and
the relays held for a working house as `held=N`.
A `land` relay is superseded only by the card leaving review, and is taken only while no
other landing of the same repo runs here: the worker it spawns is `keel/landing.py`'s, and
the pass itself never waits on a suite. Each pass also answers a landing worker that died
and, with `merge_queue` on, pre-runs one card at review (`drain.landing_upkeep`).

**A resume relay is TOLD, or HELD** (c-598). An idle house is told the relay's prompt as a
message into its own session (`tellhouse.deliver`, [houses](20-houses.md), "The user's taps, told in
place"): no new session, no stop, the app link kept, and no pool slot or memory taken, since
nothing new runs. A house that exited is resumed as before. A house the listing shows WORKING
is not touched: the relay is HELD (`drain.hold`), not taken, not noted, left pending on the
board, and so is a second resume for a card told earlier in the same pass. Its Stop kicks the
drain and the next carry tells it; a house that turned busy between the look and the tell is
told anyway, because the relay is already marked carried and the harness queues a message for
its next input. A held card is not hidden from the rest of the pass, so a house paused on a
permission prompt is still seen. A house open in the user's terminal is noted as before.

**The user's held tap wins the Stop** (c-604). While a `resume` or `stop` relay of the user's waits for
THIS house (`views.held_tap`: for the card's current session, addressed to the host that
claimed it, or to `keel-turn-end`'s own host, and under 30 minutes old, so a stale tap or
one for another session silences nothing), only the actions that would send the
house on yield: `kb stop-check`'s nudge at building (and its budget's block) records the
Stop with `tap_waiting` instead, and the turn-end news waits in `brief.md` for the next
resume. Everything else runs as on any Stop: the review gate and the record check (which act
on the turn that staged review and on no other), the drop filing, the discussion and merging
flags. The turn ends and its kick carries the user's tap first. In the sandbox the nudge at building
sent a house on without the user's Approve plan's prompt, and the held tap reached it 97 s later
with the card at review. A GATE's tap (Approve, Send back: `kb relay --gate`, and the relay
an approve or a stage move writes) records the stage the card was at once its move was made
(`data.stage`); one carried after the card moved to another stage is `superseded`, never
told stale, with a note: "the resume the deck asked for was dropped: the card moved from
building to review since the tap; tap again if it still stands" (`drain.moved_why`). Any
other resume (a comment, an answer, an Ask) records no stage and is told wherever the card
now is. The receipt says "held until the house's turn ends, then building" only for a relay
the deck held for a house it saw working (`kb relay --held`, `actions.hold_here`), never for
one to an idle house (`receipt.resumed`).

## The pools

- **`houses_max`** (the install's `config.toml`, default 3) is the number of houses this machine runs at
  once. A house counts when an agent row's name is a card id and the house is doing
  something (`drain.holds_slot`): its card is at `building`, or at `planning` with no plan
  delivered yet, or its row is `busy`, or it was resumed and no `Stop` or `SessionEnd` from
  its own session has landed since. An attended card idling at its open plan gate holds no
  slot for as long as the user takes to answer (c-262), and a
  card at `review` holds none either, which is why many cards can sit at their
  outcome gate for months without starving the board. The idle house is not ended:
  Approve or Send back resumes it as before. The resume clause covers Send back, which
  mints a new session the harness can take seconds to list as busy; a hook naming the
  superseded session (retired as part of the resume) does not end it.
- **A house the drain blocked for a permission pause is another idle case** (c-528): its card is
  at `building` but nothing can happen until the user answers, so it holds a slot only while its
  row is `busy` ("A house auto mode paused on a permission prompt", below).
- **A tracking card is the third idle case, and the stage cannot see it.** Its stage is its
  children's, so it reads `building` while a slice builds and its own house has nothing left
  to do. `holds_slot` reads `derived.tracking` first and asks only whether that card's OWN
  session is doing something. Otherwise an idle parent holds a slot and every pass
  logs `house pool full at <n>; <id> waits` while one house is working (c-277). It is
  also never reconciled (`drain.reconcilable`), and unlike a plan-gate house its idle session
  IS ended, once, by `drain.retire_tracking`: the slices carry the work, nothing is waiting
  on a human, and a later resume mints a fresh session anyway. The log line says `retired=N`
  on a pass that ended one, and the card gets a note naming the session.
- **One function says it.** `drain.house_ids` is the only place the rule lives: the drain's
  pool counts, the `houses=` and `reviews=` of its log line, and the deck's `running` list
  (`deckstate.running_of`) all read it, so the header's count of `houses_max` agrees with
  the drain.
- **Restoring a house is not starting one.** Reconcile resumes every dead house it owns,
  whatever the pools say: that house was already running and keeps its claim to its slot,
  and after a restart with four dead houses the alternative is two of them stranded at
  `building` with nobody to continue them. Only the memory floor defers a resume, because
  that is about the machine rather than the policy. What the pools bound is what the pass
  ADDS on top: the houses this pass resumed are counted into their pools (`slot_of`), into
  the browser slot and into the memory gate BEFORE any start. They are counted from the
  board (the card ids `drain.reconcile` returns), never from a second listing: the listing
  is taken once at the top of the pass and a session minted mid-pass is not reliably listed
  for seconds. Missing that count, a drain with `houses_max = 2` resumes two houses
  and then starts two more in the same pass, and logs `houses=4`
  (`<install>/history/docs/decisions.md`).
- **The human's tap is never refused.** Approve, Send back and Resume on the deck resume a
  house directly (`actions.resume_with`, then `house.resume`), outside any pass, so they
  never consult a pool: the user is answering a house that is already the user's, and a full pool is not
  a reason to queue the user's own answer. Three plan approvals with two slots therefore put
  three houses on the machine. The drain's side of the bargain is that its next pass counts those
  houses like any other (the card is at `building`, or at `planning` mid-turn by
  `resumed_mid_turn`), so a tap can take a machine over its limit and the drain never adds
  to it.
- **Reviews fill their own pool.** A card whose `options.slot` is `review` counts against
  `reviews_max` (default 2) and every other card against `houses_max` (default 3). The pass
  walks the one queue-ordered startable list and starts each card whose pool has room, passing
  over a full pool rather than stopping, so a burst of reviews cannot take a build slot and a
  queue of reviews never blocks a build behind it. The log line says both counts.

## The queue

`startable_cards` returns the startable cards in queue order (`tree.in_order`,
[cards and gates](10-cards-and-gates.md), "The card tree"), not oldest first. A card's place
is its top-level tree's place, then its own place inside that tree; each place is the
`rank` `kb next` gave it (lowest first) and otherwise the order it was filed in, so with no
rank anywhere the order is exactly the old oldest-first. The queue orders only what is
already startable: a card placed first that still waits for its `after` is not in the list
at all, so a dependency always beats a place. The deck's state document carries the same
order as `queue` (every assigned working card, startable or not), which is what the Cards
list numbers. `kb queue` says why a card is not starting: blocked, claimed, or waiting for
its `after`. (The console space's in-flight cap, c-541, went with that space in c-593.)

## This machine's limits

This machine's limits are `[keel]` keys in the install's `config.toml`; a key left out takes its default.
`keel doctor` prints the resolved line.

| Key | What it does |
|---|---|
| `houses_max`, `reviews_max` | the two pools above |
| `browsers_max` | the browser slot (unset: no cap) |
| `memory_floor_mb`, `house_mb` | the memory gate (floor 0: off) |
| `house_nice` | houses run behind voice (0: off) |
| `idle_resume_minutes` | how long a house may sit idle mid-turn with no `Stop` before the drain puts it back (default 10; 0 switches the rule off) |

- **Which spaces.** The drain serves every space (`Config.served_spaces`). A `[hosts.<name>]`
  table, a `[tenancy]` table, a `board_url` and a space's `host` key are retired: the
  config loader ignores them with one line in `Config.warnings`, never a load failure.
- **The browser slot.** A card that drives a browser declares it with `options.browser`
  (`kb create --option browser=true`). The browser it drives is `bin/keel-browser`, the only
  one ([houses](20-houses.md)). A live house holding a slot whose card declares it,
  plus each one this pass resumed or started, counts against `browsers_max`; a browser card waits and
  the card behind it still starts, as with a full review pool. It also holds its house or
  review slot: a browser counts as a house.
- **The memory gate.** One reading per pass (`machine.available_mb`: Linux `MemAvailable`,
  macOS `vm_stat` free, inactive and speculative pages). Under `memory_floor_mb` the pass
  starts nothing, not even a card named with `--card` (refused with the reading), and defers
  a reconcile's resume to a later pass; a block still happens, since it starts nothing, and
  a relayed resume happens too, because the human's tap is never refused. Each start or
  resume in the pass takes `house_mb` off the reading, the relayed one included, because a
  house takes seconds to grow and a second reading would not see it yet. With a floor set
  and nothing readable, the gate
  is shut. The log says `memory gate: <n> MB available, under <floor>; starting nothing` and
  the summary line ends `memory=<n>MB`, what is left after this pass's starts.
- **Peak memory on the card.** Every pass takes one `ps` snapshot (`machine.process_table`)
  and sums resident memory over each slot-holding house's process tree: the agent row's
  `pid` (the row carrying the card's session) and every descendant, so a house's shells,
  test runs and browser count. `options.peak_mb` is rewritten only when the tree beats it by
  `PEAK_STEP_MB` (32), so it is a `set` event when a house grows, not every pass. Sampling
  every `poll_seconds` misses a spike shorter than that; it is the budget's evidence, not a
  profiler.
- **Voice ahead of houses.** The same pass raises every process in each house's tree to
  `house_nice` (`machine.renice`, which never lowers a nice). A child a house starts later
  inherits it. On Linux, nice orders processes only inside one cgroup, so the voice gateway's unit
  carries `CPUWeight=400` against the engine's 100, where the houses live (and
  `KillMode=process` there keeps them alive across an engine restart; [cutover](80-cutover.md)).
- **Never the pass.** Peak and nice (`drain.tend`) are bookkeeping: a failure there is one
  `tending houses failed` log line, and the pass goes on.

## A house the account's limit stopped

The third way a turn can end, and the only one with no hook behind it. When
the account hits its session rate limit, houses
mid-turn at `building` end their turn with **no `Stop`**: the last event on each card
is the idle-prompt `Notification`, and `claude agents --json` lists each session as `idle`.
Reconcile wants a session GONE from the listing, and the Stop-hook nudge never runs because
no Stop fires, so they would sit at `building` holding the whole pool with no work happening,
and the limit resetting changes nothing (c-311, c-312, c-313).

**What says it (`drain.idle_stuck`, the one place the rule lives).** All of these, from the
board and the one listing the pass already holds:

- the card is one reconcile would own (`reconcilable`: at `building`, or at `planning`
  before the plan lands; never archived, never tracking, never a card Bosun builds
  (c-647), and it has a session), and it is not blocked, because a blocked card is already
  the user's;
- it has no pending `relay`, which every other step of a pass skips too;
- its OWN session is in the listing and is not `busy`. Gone from the listing is reconcile's
  case; `busy` is a house working;
- **no `Stop` or `SessionEnd` from that session since the turn began.** This is the second
  signal, and the one that protects a house that is genuinely waiting on the user: a house that
  needs an answer blocks its card (the contract's `kb block`), and any turn that ends at all
  fires `Stop`, which the nudge and the block budget answer (rung 1 below). A question asked
  at the end of a turn is therefore rung 1's business and never this rule's. The plan gate
  is the third shape, and it is never at `building`, so a plan discussion is never touched;
- the newest `Notification` of this turn is the plain `idle_prompt` and not a
  `permission_prompt`. The idle prompt fires about a minute after ANY quiet session, the user's
  included, so it cannot be the whole signal; a permission prompt names an answer only the user
  can give, and putting that house back would only ask the user again. It DOES fire under
  `--permission-prompts none` (c-521, below), and that house is blocked, not resumed.

**What it does.** After `idle_resume_minutes` of that (10 by default, a `[keel]` key, 0 to switch the rule off), resume the house through the
usual path (`house.resume`, which retires the session it supersedes) with one fixed prompt:
its turn ended without finishing, most likely the rate limit, carry on to the card's gate.
Each attempt is a `resume` event and a note on the card, so the record says what happened,
and the wait doubles: **10, 20, 40 minutes**, then a block after 80 more with the reason
`idle at building 3 times: each turn ended with no Stop and each resume ended the same way
(most likely the account's rate limit); it last said: ...`. Growing, because if the account
is still limited the resume ends exactly the same way, and asking every ten minutes for
hours would only spend the limit that is holding it up. The memory gate defers a resume like
any other (the block, which starts nothing, still happens), and nothing here sleeps: the
only clock is `drain.now`, read once per card per pass.

**It keeps its slot while it waits.** `holds_slot` reads `building` and asks nothing else,
and that is deliberate: this house is coming back, and it will need the slot when it does.
Freeing it would let the same pass start another house and over-subscribe the machine the
moment the quiet one resumes, which is the fault the pool count of a pass's own resumes
exists to prevent. It also makes the step cheap for the pools: the card is already counted
through the listing, so a resume here adds nothing to them.

**The user always wins.** Any resume that is not the drain's own (the user's Resume, an Approve, a Send
back, reconcile's), a turn that really ended, a stage move, a block, an unblock or a split
puts the count back to zero and the schedule back to its shortest wait (`drain.stuck_tries`).
So the drain can never argue with the user: the user's answer restarts the clock, and a card the user blocked
or a card at a gate is never touched at all.

## A house idle with a background job of its own

c-526 idled thirty minutes behind a background wait loop that could never end, and nothing
on the card said so: the deck read `idle`, the drain saw nothing to do. Now every pass, after
the quiet rule, `jobs_upkeep` reads the harness's job record for each house this drain owns
that the listing shows outside a turn (`housejobs.of_row`: its `state` is not `working`, since its `status` says busy while a job runs; then the session's
`state.json`, `inFlight.tasks` and the shells in its `fan`). For each job still running it
notes the card ONCE: `idle with its background job <task> still running since <time>:
<command>`, and the log line says `jobs=N`. It only tells: it resumes, stops and blocks
nothing, because a house waiting on its own suite may be doing exactly the right thing.
Since c-597 a work house does it on purpose: its full test container and screenshots run as
background jobs beside the review ([houses](20-houses.md), "Preship first"), so this note on
a work card at building is expected while they run.
The deck reads the same record for the house word ([the deck](40-deck.md)). When such a
house is stopped, its jobs end with it ([houses](20-houses.md)).

## A house auto mode paused on a permission prompt

The case (c-521, r-1): auto mode's classifier denies `git reset --hard`, then two
read-only `git show | grep`. Past its denial limit auto mode stops deciding and opens a
permission prompt for a human, sometimes with a timed auto-deny (a command
waits about three minutes, then is denied), and a bg session has nobody in front of it.
The house cannot tell it is stuck. Unseen, the card sits at `planning` with no block, the drain
counts it as a live house for half an hour and more (30+ minutes, measured), and the user
finds it by hand.

**What says it (`keel/permpause.py`, two harness facts, never a timer).** Either one:

- **the listing**: the card's own row in `claude agents --json` is `status: "waiting"`
  with `waitingFor: "permission prompt"`. Read from the 2.1.283 binary on 2026-09-26: while
  any dialog is open the session reports `waiting` and the listing prints `waitingFor`
  beside it, and a permission dialog is the one with no word of its own. Another dialog
  (`input needed`, `dialog open`) is not this rule's;
- **the hook**: the row is listed and not `busy`, and the newest `Notification` from the
  card's own session in this turn is `permission_prompt`, with no `Stop`, `SessionEnd`,
  `resume`, `session` or `unblock` since. That covers a listing that says `idle` instead.

**Which cards (`drain.permission_upkeep`).** Owned by this drain, with a session the
listing shows, not archived, not tracking, no pending relay, not already blocked, and not
done: at ANY stage (c-584). Until then only a card holding a slot (`building`, `planning`
before its plan) was looked at, so a pause at review or at the user's plan gate went unseen.

**What it does.** Blocks the card, marked `permission-pause` (`data: {paused: permission}`),
with a reason that opens with what can be done (`permpause.ACTION`, c-584), then the fixed
`permpause.HEAD`, quotes `waitingFor`, lists the
commands denied in the current turn (the transcript's tool_results since the turn's last
prompt that open with the harness's own words, "Permission for this action was denied" or
"Permission to use <tool> has been denied", never a bare filesystem "Permission denied",
paired with their tool calls, each with the classifier's bracketed reason, at most five,
clipped), names a call still waiting on an answer, and asks for a way round. A compaction
summary or a meta record does not start a turn. A command is REDACTED before it is quoted
(`permpause.redact`: a header's value, a bearer token, a `key=value` whose key names a
token, secret, password, key, cookie or auth), because the reason is on the board, the
deck, the wire and in Bosun's prompt, and a denied command is often the one with a
credential in it. While that
block stands the card holds NO house slot unless its own session's row is `busy` (`holds_slot` finds
`HEAD` in the reason, first line or second, so it needs no event), which is what that half hour costs. The transcript is the card's
CURRENT session's, from its hooks; with none, the reason says the transcript did not say.
It runs before the quiet rule, so a paused house is never put back with the rate limit's
prompt. The user's Resume answers it like any block; the mark wakes Bosun on ANY card
(`pausewake.wakes`, c-584; "A paused house: the wake", below). The block does not end the session: nothing automatic
does.

**When the prompt closes by itself** (D1 of c-528): when the drain's own block still
stands, with its exact text, and the SAME session carried on (the listing shows it `busy`,
or a `Stop` from it landed after the block, which covers a turn that went on and ended
between two passes), the drain clears it (`kb unblock --expect <reason>`) and notes it, only when the block really came off. "The same session" is board facts: no
`session` event since the block. A
block with any other text, or a new session, is never touched. A house that pauses again is
blocked again.

## A space whose login expired

The quiet shape has a second cause. When a space's OAuth cannot
refresh, every house turn ends at once on `Login expired · Please run /login` with no
`Stop`: listed, idle, at `building`, exactly the rate limit's shape. A drain that calls it the
rate limit spends its resumes on a login that cannot work, and a doctor that says
"logged in" because it only looks for a credential file leaves the user to ask why the
house is idle.

**The words (`keel/login.py`, `LOGIN_WORDS`).** What Claude Code 2.1.281 prints for a login
that is gone, read out of the installed binary: `Login expired`, `Please run /login`, `Run
/login to sign in again`, `Not logged in`, `OAuth token revoked`, `OAuth token has expired`,
`Invalid API key`, `Authentication required · Sign in again`, matched without regard to
case. The house leaves the same text in its transcript as an assistant record with `"error":
"authentication_failed"`. Two of its auth messages are left out on purpose: "Could not
refresh your login because another Claude Code process is refreshing it ... Try again in a
minute" and "Authentication error · This may be a temporary network issue". Both pass on
their own.

**The probe (`login.check`).** One real call under the space's config dir,
`harness.login_probe`: `claude -p "Reply with the single word ok." --no-session-persistence
--model haiku --strict-mcp-config --tools ""`, in the space's environment without the user's token,
its own process group, 45 seconds at most. It answers `good` (exit 0), `expired` (the words
anywhere in what it printed; recorded under a config dir with no login: `Not logged in ·
Please run /login`, exit 1, under a second) or `unknown` (a timeout, the network, a rate
limit, anything else). `unknown` is never read as expired. The answer is kept per space in
`state/login.json` with its instant, and a space is probed at most once in ten minutes on the
drain's own (`PROBE_EVERY`). It is a reading of the machine, like `drain.log`, never the
reason a card moves on its own.

**When it is asked.** For a quiet house (`drain.quiet_login`): at once when the words of its
CURRENT turn name a lost login (`drain.turn_said`, the transcript the hooks recorded and then
the log; not `last_output`, whose newest Stop message is an older turn's, since a quiet turn
has none), and otherwise just before the quiet rule would spend a resume. Words the probe
contradicts (it says `good`) leave the ordinary rule in charge; words it cannot confirm
(`unknown`) leave the house alone until the next probe rather than resume it into the same
wall.

**What an expired space gets (`keel/loginhold.py`).**

- Its quiet houses, and any of its houses that exited, are blocked with one reason: `the
  <space> login expired, so its houses cannot run: run CLAUDE_CONFIG_DIR=<dir> claude, then
  /login; they resume on their own once it works` (the default profile's fix names no
  variable). A dir that never held a login (`login.ever_logged_in`) says `the <space> space
  is not logged in` instead of `login expired` (`login.gone`, which the drain's log lines
  use too, c-560). A `.claude.json` that cannot be read or parsed (Claude Code caught
  mid-write) answers neither way, and the words fall back to `login expired`. They show
  under needs-you. No resume is spent.
- The mark is the `set` of `options.login_hold` to the space recorded directly before the
  drain's `block`. `loginhold.held_space` reads events, not the reason's prose: walking the
  card's block and unblock events and the set events that touch `options.login_hold`
  newest first, the first must be the drain's block and the next that set. A set of any
  other option is passed over: the block's own drop of a re-offer ask and a voice hold
  taken since both record one (c-651) and say nothing about the login. The user's unblock, the user's own block, or a later block of the drain's for
  something else comes first, and the card is never touched.
- No new house starts in that space while it is expired; the other space is unaffected.
- Each pass probes the expired space again (still once in ten minutes). Once it says `good`,
  every card the drain held for it is resumed once through `house.resume` with its own
  prompt, then unblocked, its mark cleared, and a note says so (`drain.login_upkeep`, log
  `relogged=N`). A resume that fails leaves the card blocked with the failure noted. A
  held card Bosun builds (c-647) is unblocked the same way with NO resume
  (`loginhold.release`): its mark cleared and a note, and it is not counted in `relogged`. The
  memory gate defers the rest, and the resumed houses are counted into the pools like
  reconcile's.

**What the user sees.** `keel doctor` probes every space this machine serves (always, the user asked)
and says `logged in (probed HH:MM)` or `LOGIN EXPIRED (probed HH:MM): run
CLAUDE_CONFIG_DIR=<dir> claude, then /login`;
`NOT LOGGED IN` instead when the dir has never held a login: no `.credentials.json`, and
no account in its `.claude.json` (the default profile's is `~/.claude.json`), a fresh
install (`login.ever_logged_in`).
The deck's health turns red with `login: <host> Claude <spaces> expired` (the space's dir is
a row of the Logins list, below), a login ask names it, and Now and Attention open with a
banner carrying the fix ([the deck](40-deck.md)).

## Every credential: the Logins list

A space's probe covers only the dirs a drain's houses run under. A voice turn
connected to a work card can fail with `Failed to
authenticate: OAuth session expired and could not be refreshed` while health stays
green, unless the words are in `LOGIN_WORDS` (they are: `oauth session expired`) and the
talker's dir is probed too.
`keel/logins.py` is the list that closes that (c-558).

**The rows** (`logins.specs`): one per distinct Claude config
dir in use (its served spaces' dirs, the talker's where the talker is installed, Bosun's
where Bosun lives), `drive` where the backup store is rclone,
`google-tts` and `jev` where the voice gateway is installed, and whatever an adapter's
optional `logins check` verb returns (`<space>:<id>`; the work adapter's asks its code host
and its tracker for the account behind each token: a 401 is `expired`, and a 403 is
`unknown`, since a working token whose scopes leave out the account read answers 403,
c-560). A typical install has `claude:work`, `claude:personal` (Bosun's too),
`claude:harbor` (the talker and voice), `drive`, `google-tts`, `jev` and the adapter's rows.

**State from events first.** A failure marks its row expired at once, and the next pass
checks it: `logins.saw` for a turn whose output names a lost login (Harbor's voice turn in
`harbormsg.report_failure`, a connected house turn on the machine that ran it
(`housetier`, `converse.take_turn`'s one-shot), and the talker's own output);
`bin/keel-backup`'s refused store (`keel logins mark drive`, and `--ok` on the next run that
reached it); a failed fetch whose output names a refused credential, for the rows its
`segment.md` declares (`logins: google-tts` on cloud-spend); and the gateway's own 401 or
403 from Google TTS or Jev (`harbor_voice/loginmark.py`). A mark newer than the last check
wins until a check settles it: a good one drops the mark, a red one confirms it, and an
`unknown` one does neither, so the row stays red and is checked again at `RED_EVERY`, not a
day later (`logins.settles`, `logins.pending`, c-560). A key's good check settles nothing
either: it only sees that the key is there, so its mark stays until a real success: the gateway's next 200 after the Logins file
changed (one `stat` a call), so a mark from a refused fetch, from before a restart, or its
own comes off on the first call that works; `keel voice key set` restarts the gateway onto
the new key, and its first spoken sentence is that call. The gateway and the talker mark
into the state dir they already know (`logins.mark_at`, `saw_at`), never a config they
would load, so the voice selftest's scratch home is all they touch.

**Then a cheap check** (`keel/loginprobe.py`), at most two a pass, most due first: a row
marked since its last check, or still holding a mark its last check settled (the hold's probe
writes `login.json` before the list's pass, and only the list's own check drops a mark, so a
refuted one is dropped in that pass and a later `unknown` probe cannot revive it, c-560), one
red for ten minutes (`RED_EVERY`), one never checked, one a day old. A Claude dir is the space probe's one word on haiku, which costs nothing when the
login is gone, plus the instant its refresh token ends, read out of `.credentials.json`
(measured 2026-09-27: `/login` plus exactly 30 days, not moved by an access token
refreshing). It is the very probe the hold and its release make (`login.check`), so the
list never holds a dir the release then finds working (c-560); an expired answer from a dir
that never held a login (`login.ever_logged_in`) is `missing`, and under no login the probe
answers locally in under a second, with no turn. Drive is `rclone lsd`, a voice key only
set or `unset` (Keel never reads either key: its validity is the gateway's 401; on macOS
only `security`'s exit 44, item not found, is `unset`, and any other failure, such as a
locked keychain, is `unknown`), an adapter its verb. Both voice keys are optional and install leaves an
empty file for each, so `unset` is not red: it raises nothing and leaves health alone
(c-560). A space dir's answer is kept in `state/login.json`, which the hold above reads,
with `missing` kept there as `expired` (`logins.for_hold`, c-560): the hold and the doctor
know good, expired and unknown, and a dir with no login is one whose houses cannot run, so
the hold must fire for it. Every other row's answer is kept in `state/logins.json`,
with its last mark and `good_at`, when it was last seen good. `keel logins` lists them,
`keel logins check [--all]` checks the due ones (or all) now, and `keel logins mark <id>
--why <text> | --ok` is the script's way in.

**What the user sees.** Health is amber for any red row, red for an
expired dir a served space's houses run under, amber for a Claude login two days from its
end ([the deck](40-deck.md), "The Logins list"). A red row raises one **login ask**
(`keel/loginask.py`, raiser `drain`), raised by the drain each pass. A row red only for a
mark no check has settled yet (`unverified` on the row) asks nothing yet: words can mark
falsely, the asks are synced while the board is open and before that pass's checks, and
the next pass checks a marked row first, so a false mark never puts a raise-then-withdraw
ask on the user's Needs you (c-560). A mark only `unknown` answers have followed asks once it is
two `RED_EVERY` periods old (`logins.UNVERIFIED_FOR`): a broken login and a flaky check
look the same to the user. One ask per red episode (since the row was last good), naming
the credential and its one-liner, withdrawn by the drain when the row answers good, or (a
voice key) reads `unset`, since an optional key no longer set is not red (c-560). The user's
answer (A Logged in, B Later) is recorded and marked told at once, as the deploy ask's is:
there is nothing for Bosun to do, and Bosun may not withdraw it. A Later is not asked again
until the row has worked and failed again.

**Why not `claude setup-token`** (c-558, decision D1). Measured in Claude Code 2.1.283: it
mints a 365-day token scoped to `user:inference` only, and the harness refuses Remote
Control with it ("Remote Control requires a full-scope login token"). Every house, Bosun and
the talker run with `--remote-control`, so the dirs keep `/login`, and the list says two
days ahead when one is about to end.

## Recovery: three rungs, all facts

| Rung | Signal | What happens |
|---|---|---|
| 1, inside the house | the `Stop` hook fires with the card still at `building` and no stage move | `kb stop-check` answers `{"decision":"block","reason":...}` and the session continues its own turn. At most twice; the third sets `blocked_reason`. A tracking card is let go instead: its stage follows its children, so there is nothing to ask for |
| 2, in the drain | `SessionEnd`, or the row gone from `claude agents --json` | resume once with `claude --resume <id> --bg`; a second exit blocks the card with the last thing it said |
| 3, in the drain | the session is listed and idle, and no `Stop` since the turn began (the rate limit, above) | resume it after 10 minutes, then 20, then 40; block after three attempts with what it last said. If the space's login has expired instead, block it for the login and resume it once the login works |

## Where a card starts: the space and the repo

A card can need something this disk lacks: a repo that was never cloned, a project under the
projects directory. So `startable_cards` keeps a card only when `where.startable_here` holds
(`keel/where.py`):

- **the space.** The card's space is one this drain serves, which is every space.
- **the repo.** Every repo the card names is a directory on this disk (a listed repo or a
  project), or it is a new-project card and this machine has the projects directory. A
  space with an adapter is not checked: its adapter owns where its repos are.

There is no pin and no placement between machines: `where.py` only says why a card cannot
start here. A card that cannot is not an error: the deck says so (`waiting`, [the
deck](40-deck.md)), with the "Cannot start this: ..." line `where.waiting_text` writes.

The listing a pass reads covers every space (`Config.local_spaces`), so every house here
holds its slot and is reconciled.

Quiet alone still infers nothing. A session waiting on a human is at `planning` or `review`
by construction, or it has blocked its own card; the one thing the drain now reads out of
quiet is a turn that ended with NO `Stop` at all, which is not a house waiting but a house
cut off ("A house the account's limit stopped", above). Every other silence is left alone.

## Restarting itself when the code moves

The drain notes the commit it started on and, between passes only, compares it with the
checkout's `HEAD` (`merging.code_head`). When they differ it logs "code moved since start"
and execs itself with the same arguments, so a merge into `~/keel` main never leaves a
stale drain running old code. Never mid-pass: a restart interrupts nothing. **The config
counts too** (c-618): `drain.config_moved` compares the config file's mtime and size with
what they were at start (`drain.config_stamp`), so a repo or a space added in the deck's
Setup view ([onboarding](89-onboarding.md)) is served after the next pass, through the same
wait for quiet below, and logs "config moved since start". A moved config is loaded first
(`drain.config_loads`); one that does not load is logged "config moved but does not load:
<error>; keeping the running one", re-stamped, and not exec'd into.

**As it starts, it brings up a service the install is missing** (`appservices.upkeep`,
c-742). A deploy restarts the drain onto the new code, and that start is the one place new
code runs on an existing install without a hand step, so it is where a service added since
the install was made appears: `appservices.bring_up` installs and starts each service the
install never had (the fetch role's, for an install made before c-742: no unit rendered in
its own `services/` folder), and logs `service <label> was missing: installed and started`,
only once the manager reports a process for it (c-747): one it loaded that has no process
is a failed step, stays installed, and is started, not reinstalled, at the next drain start.
It does this once per start, only on an install whose drain unit is installed and names
this install, never for the deck or the drain themselves, never for a service its owner
uninstalled or stopped (the rendered unit stays, and is the record), and it never rewrites, stops or
restarts a service that is there ([install](88-install.md), "Services"). A failure is a failed step in the log and a
sighting, never a drain that does not start.

**It is the deck's restart too, and it waits for quiet** (c-557, r-25,
`keel/restart.py`). `keel run --roles drain,serve,fetch` is one process, so the exec
restarts the deck with it. Two facts follow. `os.execv` keeps the pid and the process start
time, so `ps` cannot say whether a process runs today's code: a pid started days ago may be
running code from minutes ago, which `drain.log`'s "code moved since start" line on each
restart shows. And the exec cuts a
connected voice conversation, whose pipes do not survive it. So the restart waits while the
process holds a conversation or is opening one (`housetalk.Sessions.busy`), or is answering a
house call or a deck action (`restart.CALLS`), logging "the restart waits: <why>" once per reason.
Nothing bounds the wait but the conversation: the idle hold's reaper closes one the user stopped
talking to, and nothing automatic ends one the user is in. The head the process LOADED is written to
`state/drain.json` (`head`, beside `pid` and `kinds`, and `waiting` and `since` while it
waits), which `keel doctor` reads.

Two things it does not hold, on purpose. The Voice app's websocket spliced through the
deck is not a call here: the app keeps it open for as long as it is open, so holding it would
hold the restart for as long as the phone shows Voice, and the app reconnects by itself. And
the passes go on while it waits, on the code the process loaded, against a checkout that has
moved: a module imported lazily in that window comes from the new code. That window used to
be one pass (a deploy moves main mid-pass); it is now as long as the conversation, which the
reaper bounds. Holding the passes instead would stop every house start for that long.

A head that cannot be read is **unknown**, and unknown reads as "not moved". Every git
`merging` runs carries a timeout, and a timeout is `subprocess.TimeoutExpired`, which is a
`SubprocessError` and not an `OSError`: `merging.git` turns it into `MergeRefused` so that
`code_head` answers None for it, because this check is one of the few things `drain.run`
calls OUTSIDE its try, and an exception here ends the loop rather than one pass. On a
loaded machine a slow `git rev-parse` does exactly that (`<install>/history/docs/decisions.md`).

## A card voice is talking to

`options.voice_hold` on a card means voice has stopped that house's process on purpose and
is taking turns into its transcript ([the talker and voice](50-talker-and-voice.md)). For
as long as the hold is live, the pass leaves the card alone: `reconcile` does not resume it
(its session being gone is the conversation, not a house that exited), `retire_tracking`
does not stop it ("connect me to c-277" is the obvious thing to say to a card that was
split), `resume_quiet` does not read it as stuck, and a relay tapped on the deck is
superseded with the reason rather than carried into the middle of the conversation.

`release_holds` is the first step of the pass and the repair. A hold carries an expiry
([keel] `voice_hold_seconds`), so a conversation the user walked away from clears itself: the
hold goes, and a house voice STOPPED is woken with `house.wake` (no prompt, no model turn,
the same session id). A house voice found already down is left down, and so is one on a
card Bosun builds (c-647: the hold is cleared, with a note, and no house is woken, since
that card is never a house's; when its conversation would not close, the note says exactly
that and that no house is put back, `BOSUN_CLOSE_FAILED_NOTE`, where a house's card is told
the next pass puts its house back). The hold is cleared
BEFORE the wake, because a wake that fails leaves an ordinary exited house, which
`reconcile` already knows how to put back once, while keeping the hold on would have the
drain trying the same failing wake every thirty seconds forever. Every card released this
way is skipped for the rest of the pass (the listing predates the wake, so every later step
would read the house as exited), and a woken house takes its pool slot and its `house_mb`
like any other.

## A card the user dropped into from a terminal

`options.dropin_hold` means Drop in handed the user `claude --resume` for the card's exited
house ([houses](20-houses.md), "Drop in"), so the user is in that conversation at a
terminal, or about to be. The pass leaves such a card alone exactly as it does a voice hold:
`reconcile`, `resume_quiet` (through `idle_stuck`) and `retire_tracking` all skip it, and
a relayed resume is refused by `house.resume` and noted. `dropin_upkeep` runs beside
`release_holds` and is the hold's only clock: it marks the hold `seen` the first pass the user's
terminal session is listed (`kind: interactive`), ends it when a seen session has left
the listing, and ends an unseen one when its `until` passes. A released card is skipped for
the rest of that pass; the next pass treats it as the ordinary exited house it is.

## A failure it keeps seeing: a request to Bosun

A step that fails is logged and the pass goes on. So that a failure repeated every pass does
not live only in a log file, the drain also SIGHTS it (`drain.sight`, `keel/requests.py`):
a start that failed (key `drain:start:<card>`), a resume it could not carry out, relayed,
quiet or after a voice hold (`drain:resume:<card>`), and a step that raised
(`drain.failed_step`, `drain:step:<name>`: the upkeeps, tending houses, the tracking close
and the pass itself). The `[console] repeat_after`-th sighting of one key inside
`repeat_minutes` (3 in 60) opens a request to Bosun; a sighting of one already open only
counts up on it. An expired login (its own hold, below) are not sightings. Nothing here wakes Bosun or
touches the card beyond the note it already writes; see [Bosun](96-bosun.md), "Requests".

## The user's answers to Bosun: the wake

First, where Bosun lives, a voice hold on Bosun that ran out is repaired
(`drain.bosun_hold_upkeep`, c-523): the conversation is closed, Bosun is woken if voice
stopped it, and the hold is cleared, as `release_holds` does for a house ([Bosun](96-bosun.md),
"Harbor and Bosun").

Where there is a Bosun (`console.configured`: an install, or a config whose `[console]`
table names a `host`) each pass tells Bosun the answers the user gave its asks
by tap or voice (`drain.answers_upkeep`, c-521). Only when Bosun is up and idle
(`consolewake.can_wake`): it claims the waiting answers (`kb console claim --via wake`), and `consolewake.wake` sends Bosun a MESSAGE naming
them into its live session (`relay.tell`, c-530): a one-shot `claude -p` named `keel-drain`
whose only tool is SendMessage. Nothing is stopped or resumed, so its session id and app link
never move. Bosun reads the answers with `kb console hook`, which takes the claim and
confirms them. The claim is a lease on pointing: one nobody confirmed runs out in ten
minutes and the answers are pointed at again, twice at most (`asks.POINTS_MAX`, the ask's `pointed` moves); a
failed relay rests every wake for 15 minutes (`consolewake.resting`). A working, stopped,
stuck or never started
Bosun is not woken, and the answers wait for the hook atop the user's next message. A relay that
certainly failed hands its answers back (`unclaim`); one that may have sent keeps the claim.
Either leaves Bosun as it was and is sighted as `drain:step:answer-wake`. The drain never starts Bosun's session; see
[Bosun](96-bosun.md), "Asks".

## A paused house: the wake

Right after the answers, the same machine's pass wakes Bosun for the houses auto mode paused
on a permission prompt, on ANY card in any space (`drain.pause_upkeep`, c-584,
`keel/pausewake.py`): `kb console wakes` names each card whose drain block marked
`permission-pause` still stands and is newer than its last `wake` event, `consolewake.wake`
tells an idle Bosun, by message, in one prompt of ids and fixed words
(`pausewake.wake_prompt`), and `kb console woke` writes a `wake` event on each, so a pause
wakes Bosun once. Bosun raises an ask naming the card. A Bosun that is not idle is left
alone and the cards wait a pass; a wake that raised is sighted as `drain:step:pause-wake`.
At most one wake a pass (`drain.wake_upkeep`): the answers first. The same wake carries the
user's taps on Bosun's own work (c-734): a card the page filed for Bosun, and a gate tap on a
card Bosun builds, each a `tell` event newer than the card's last `wake`, listed by the same
`wakes` and told in the same message ([Bosun](96-bosun.md), "Telling Bosun"). Nothing else
wakes Bosun: a house's states (a staged plan or outcome, a block, a failed resume, the review
limit) went with driving in c-593. No timer is involved; see [Bosun](96-bosun.md), "A paused
house".

## Deploying the living house (c-600)

c-600 replaced the review round (a fresh session per round, the card sent back to building,
the user's Approve at review posting the round's replies) with the living house and the user's Ship. The
cards in flight are carried once, by `bin/keel-shipping-upgrade` (`keel/shipupgrade.py`),
which never stops, starts or resumes a session:

1. Pause the drain (`drain_paused`), so no batch is told and no round starts while the
   code and the board disagree.
2. Deploy.
3. `bin/keel-shipping-upgrade` prints the plan (a dry run; `--deck <url>` prints it from a
   live deck's state, read-only). For a card at shipping with an old answered round: the
   round's items copied into `told`, each recorded as posted (`LEGACY`) so nothing is said
   twice. For a card mid-round (at review or building with a round's batch): the batch back
   in `pending`, due at once, so that after the user's Approve (now a plain publish, which moves
   it to shipping) its house is told those items and judges them with verdicts, and the user's
   Ship pushes the round's commits. The old `ship_now` option and `rotated` flag go. The user's
   Approve at review on a card not carried yet is refused with that instruction, never a
   plain publish that would lose the round's replies.
4. `bin/keel-shipping-upgrade --run`, which also rewrites the settings files (the house's
   settings of each shipping card: the shipping deny list and the guard hook with the
   card's id). A settings
   file that already says what a rewrite would (`house.settings_current`) is neither
   proposed nor rewritten (c-604); from a deck's state, which cannot read it, it is. A house
   started before the deploy runs under its old settings until then; it reads the new file
   at its next tell or resume (whether a LIVE session rereads it is still to be checked), and the adapter's own refusal holds meanwhile.
5. Unpause the drain.

## Deploy: the ask, and the user's Yes

A repo in `[integration]` (Keel: `next`) takes every approved outcome on that branch, so
nothing is live until the user deploys ([cards and gates](10-cards-and-gates.md), "The integration
branch"). Right after the landings, the pass runs `drain.deploy_upkeep` (`keel/deploy.py`),
for a repo whose trunk this machine owns (Keel's own `~/keel`):

- **The ask** (`keel/deployask.py`, the user's D3). When `next` is not contained in main, the drain
  raises an approval ask, raiser `drain`: "Deploy next to main? It carries c-601, c-602", the
  cards read from `next`'s landing merges (`(c-NNN)` in their subjects). Option A (Deploy)
  carries the facts: the repo, the sha it pins, the cards. One ask per sha: `next` moving
  while it is open withdraws it and raises another; an answered one (Deploy or Not yet) is
  not raised again until `next` moves. Only the user's tap or voice answers it (a chat answer
  Bosun records is refused, and Bosun may not withdraw it), and the user's answer is marked told as
  it is recorded, because it is the drain's to act on, never Bosun's.
  `kb console deploy [--preview]` is the same Yes from a terminal or Harbor, the user's alone.
- **The user's Yes** starts `python3 -m keel.deploy <a-N>` in a session of its own (a `deploying`
  record on the ask first, so a second pass never starts two; a worker that died is answered
  `refused`). It starts at once, not at the next pass: the `kb` that recorded the user's answer
  kicks the drain ("The kick", above), whose thread runs `deploy.kicked`, the same start the
  pass's step makes (c-636; until then a tap waited up to a 30 s poll while the page still
  showed the previous deploy). **What makes it start once is the board**, not a lock: the
  start is a claim (`deployask.claim`) that, in one write transaction (`BEGIN IMMEDIATE`),
  re-reads that the ask is still untaken and writes its `start` record, and only the drain
  whose transaction wrote it spawns the worker, so the kick thread, the pass and a `keel
  drain --once` in another process never start two. The worker itself refuses (exit 1, the
  ask untouched) when the newest `deploying` record names another worker that is still
  alive (`deploy.take`). `deploy.STEP_LOCK` only keeps one drain's pass and kick thread from
  answering a dead worker and starting at once. **The phases are on the record** (c-636):
  until a worker takes it the ask reads `starting` (the user's answer, not yet taken:
  `deployask.untaken`, the test `to_start` uses, so it is true before the drain has run and
  is never written), worded "it starts when the drain takes it", never "now", since nothing
  on the board knows a drain heard the kick; untaken for longer than two drain polls
  (`poll_seconds`, the deck's `shipped` read) it reads waiting for the drain, unless another
  Deploy of the repo still has a live worker, which the drain holds it behind on purpose
  (`deployask.worker_busy`); then each `deploying` move
  names its phase as it begins, `start` (the drain took it, and the worker's pid), `merge`
  (the tree built, main merged in when it moved), `suite` (the full suite runs, or a full
  green run of this exact tree stands), `live` (main moved), and the end, `deployed` or
  `refused`. `deployask.steps_of` reads them back, each with its time, and a record from
  before the phases had names reads as the phase `deploying`. Under the repo's landing lock it checks out the pinned sha in a temporary tree,
  merges main in when the user committed to main since, then, for Keel's own checkout,
  asks **the preflight** (`keel/deploypreflight.py`, `deploy.preflight`, c-725): the tree is
  refused, before any suite, while the install would read a path the tree removes or would
  lose one owner's things the old tree held. It checks every path-valued setting
  (`settings.PATH_KEYS`: a space's `config_dir`, `contract`, `projects_dir`, `pipeline` and
  `repos`, and the `[machine]` paths) and each `adapter`, counting only a path the live
  checkout tracks and the tree drops, since the deploy tree is a fresh checkout with no
  untracked or ignored file in it (r3.F9); every service file whose
  `KEEL_HOME` is the checkout, in the install's `services/` or in `~/Library/LaunchAgents`,
  loaded or not (one not loaded is named with its removal, since it loads at the next login;
  the old engine's `dev.keel`, which no install command renders now, with its bootout and
  removal, r3.F8;
  one with no `KEEL_HOME` is not the checkout's): one with no `KEEL_CONFIG` while the tree
  drops the checkout's `keel.toml`, one whose `KEEL_ADAPTERS_DIR` adapter the tree drops and
  the install's packs cannot stand in for, one whose `CLAUDE_CONFIG_DIR` rulebook the tree
  drops while the install holds none; and, when the tree drops anything `shipyard
  move-personal` moves, whatever a move from the live checkout would still bring in
  (`movepersonal.pending`); and each line of the install's own text (its memory, the
  talker's rulebook among it, its identity profile, its space files, each space's config dir
  `CLAUDE.md`, and its own packs' text and brief code, their tests aside) that names a
  checkout path, absolute, from `~` or as `$KEEL_HOME/`, that is nowhere in the tree
  (`install_text`, c-726 r1.F1, r2.F6; the fix it names is a memory card, a pack card, or the
  owner's own edit, by where the file is). A path setting is refused with the fix that clears
  it: the move for a space's `contract` or `pipeline`, an edit of the install's `config.toml`
  for any other key (`setting_fix`, r2.F1). When launchd cannot say which agents are loaded, that is a
  problem, never a pass. Each problem names the one command that clears it. **The worker
  runs the live code**, so the preflight guards the deploys after the one that adds it: a
  tree that both adds it and removes something is never deployed in one step. Then it **runs the FULL suite, every module
  with the voice selftest, once per deploy** (c-646, the user's note: the deploy suite includes
  voice). The deploy is the gate that runs every module; a landing runs only `make test`
  (the core suite and what its change reaches) for speed, and nothing else runs
  `make test-all` on a schedule. The command is `[deploy_tests]` (`make test-all` for Keel;
  a repo without an entry, or with a blank one (dropped at load), runs its `[tests]` with `KEEL_FULL_SUITE=1` set, which Keel's `make
  test` answers by running `make test-all`, so a config from before c-646 still deploys on
  the full suite), with the live checkout's `.venv-voice` linked
  in. A machine without the venv refuses, and so does a run whose output says the voice
  selftest was skipped, says the change did not reach it (the selector's
  `voice selftest: not run, ...` line, `merging.VOICE_UNREACHED`), shows no pass of it
  (on any leg, the rerun included, a skip note refuses: it exits 0 too), or
  says it chose its modules (the selector's `running N test module(s):` line,
  `merging.NARROW`): each is a run narrower than the deploy owes.
  **It runs no suite when that tree is one a full run already proved** (2026-09-26, c-544,
  c-646): a landing on the integration branch links the venv into its merged tree and records
  the tree id in `state/tested-trees.json` (the newest 100, `merging.record_tested`) only
  when its run was every module with voice passing (`merging.ran_whole`: the selector fell
  back to `make test-all`; `merging.voice_passed`, a `voice: ..., exit 0` line and no skip
  note, since the skip exits 0 too; the venv linked only when its python is executable, as
  the Makefile's `-x` asks), so a landing's narrow `make test` records nothing; `kb tested
  <sha>` after a real green `make test-all` records the same, and is refused without one. The deploy compares git's tree
  id, so a trunk merged in, a manual push or a missing record is a new tree. The ask's record
  says which it did ("... on this exact tree at c-N's landing, so it was not run again", or
  "the full suite was green (voice included)"). On red it runs `[retests]` once (`make
  test-again LOG=<the red log>`, which reruns only what the log names as failed,
  `tests/parallel.py --rerun`) and deploys only if that is
  green, saying which failures passed on the rerun in the ask's record.
- **Then main moves**: the live checkout, still on main at the head it was built on and with
  no tracked change, takes the tree by `--ff-only`, and `next` follows when it is still where
  the ask pinned it. The code-moved check restarts the drain and the deck, once quiet (the
  deck by its own `serve.follow_code`, c-637). Every deploy says main moved on the ask (the
  `live` phase); a deploy of the checkout Keel runs from says so as "main is at <sha>; the
  deck restarts onto it", and
  writes `deployed` once `/api/health` answers with that `serve_head`, or after
  `deploy.deck_wait` (60 s and two drain polls, since a deck sharing the drain's process
  restarts between its passes) saying the deck has not restarted yet. Either way it is
  `deployed`, and the record's `deck` says which (`true`, or `false` when the deck was not
  seen on the new code or could not be checked; absent for another repo), so the Bosun page
  reads "deployed, deck not restarted" then; main stays moved
  either way, and nothing after it can turn the deploy into a refusal. A refusal (red twice, voice, main moved, a conflict) moves nothing, is
  recorded `refused` on the ask, and is filed at once as an open console request for Bosun ("deploy of next (<sha>)
  refused: <why>", no key, so no repeat is needed to show it). Logs: `logs/deploy.log` and the suite's own `logs/deploy-<repo>-suite.log`.
- **What it refreshes** (c-538, r-14). The `deployed` record carries `refreshes`, said in its
  text too, from the files main's move changed (`keel/refresh.py`, `effects`): always the
  drain and the deck, each once quiet; the voice gateway when `voice/`, `bin/keel-voice-gateway`, `keel/configpath.py`, `keel/childenv.py` or `keel/memoryroot.py` changed;
  and Harbor's memory (`<checkout>/talker/memory/`, and the shipped rulebook
  `templates/memory/talker/CLAUDE.md`; an install that holds its own memory is stamped from
  its memory repo instead, c-722, its own rulebook among it, the shipped one only for a
  memory seeded from the template, as `talker.Paths.rules_src` decides, c-726 r1.F5), which retires
  the voice conversation and rotates the phone talker. The worker only describes: each piece
  notices its own change from HEAD at its own safe moment ([the talker and
  voice](50-talker-and-voice.md), "What a move of main refreshes"). Without it a deploy leaves the gateway on old code
  and the voice conversation on old memory, until both are reset by hand (c-523).

## Idle houses at shipping and after a merge (a-72)

`drain.idle_upkeep` runs after the shipping watcher in every pass (`keel/shipidle.py`), over
the cards whose session this pass's listing holds, on this machine, in a space it serves.
It owns three ends of an idle house, two decided with the user on ask a-72 and one on the user's
explicit word (c-651):

- **Done by a merge** (`options.shipping.facts` state `merged`, c-793): once the harness lists the house
  idle, it is ended (`housejobs.stop`) with a note marked `merged-end`, final. Working, it
  is left; a later pass ends it once idle.
- **At shipping, idle over `[keel] ship_idle_hours` (2 by default, c-633)** since the current session's newest
  `Stop` hook with no turn started since (`views.turn_ended`; a batch told into the session
  writes a `resume`, so it restarts the clock), unblocked, with no tap of the user's pending and not
  dropped into: closed like the user's Close idle house (`closed-idle`), so its next review batch,
  the user's gate answer or Resume brings it back with its conversation. A house with no Stop
  on record is never closed.
- **At shipping, its turn on a re-offered batch ended** (c-651, the user's explicit word: idle houses
  must not hold memory): the newest batch is a re-offer (`kb ship <id> reoffer`,
  `options.shipping.reoffer.batch` is the `round`), and its OWN turn has ended, read by the
  board's order of events and never by comparing two machines' clocks
  (`shipreoffer.batch_turn`): the first turn start after the tell (`after`, recorded as
  `started`) and then the first `Stop` of that session. Closed at once the same way
  (`closed-idle`), with `reoffer.closed_at`, so it is closed once. A turn started after the
  batch's (the user's Talk or Resume, a newer batch), or a hold the user took since the tell (the user's voice,
  whose `Board.hold_voice` records one `set` event when the hold is taken, or the user's Drop in's
  `options.dropin_hold`), makes the re-offer over (`reoffer.done_at`), and it never closes
  that turn or any later one. The card says it ahead: `derived.ship_idle` carries `reoffer`
  with `close_at` at the turn's end, and the deck reads "closes now". The marks are written by
  `Board.mark_reoffer`, which re-reads the record in its own transaction and changes only
  the mark, so a Ship that lands while the house is being stopped keeps its `posted` and
  `heads`. A normal batch keeps the two-hour close above.

**A turn that ended is not an answer** (c-654). c-151's house ended its turn on a
re-offered batch of four comments with no verdict on any, and the close's note said it had
answered that batch. So when that batch's turn ends, the batch's items with no
verdict since they were told are counted (`shipreplies.unjudged`, the same reading the
comments page's "judging N" makes). With none, the note says its turn on the batch ended,
never that it answered. With any,
the idle house is still closed (memory is the user's concern), the note says N of M items were
left unjudged, the mark keeps their handles (`reoffer.unjudged`), and the card is BLOCKED
for the user with them named, so it shows under needs you. The block has a
mark of its own (`unjudged`, `board.MARKS`). It is THE USER'S and not Keel's mechanics: it is how
the card needs the user, so Bosun's unblock, resume and retry repairs are refused on it. A
blocked card is otherwise not
watched: this one is still looked at (`shipping.watched`, `shipreoffer.awaits_him`), so a
merge of its pull request still closes the card and a decline is still said, while nothing
is told to its house until the user unblocks it (review seen meanwhile waits in `pending`). The
block says so: the card needs the user's re-offer, and reviews wait until the user unblocks. The move
to done lifts the block in its own write, saying why on the unblock it records
(`Board._clear_stale_block`): the unjudged items are moot once merged, and a done card left
blocked would sit under needs you asking for a re-offer nothing accepts. A move to done
that is refused lifts nothing, so the block is never gone while the card stays at shipping.
A decline closes nothing, so the block stays.

The turn has ended, for this, in three ways. Its `Stop`, with the house listed idle, which
is closed. The harness saying the session itself ended (a `SessionEnd` of the batch's own
session, `shipreoffer.EXITED`: the house exited, or never took the turn). And its `Stop`
with the session listed no more and no `SessionEnd` on the board (a reboot, a killed
process). The last two close nothing, the re-offer is over (`reoffer.done_at`), and what
the turn left unjudged is handed to the user the same way; they are the cases in which this step
looks at a card whose session the listing does not hold. A listing that failed reads as an
empty one, so the third asks the harness again and strictly (`shipidle.unlisted`): a failed
listing settles nothing. A house the drain stopped always gets its `closed-idle` note,
even when the record moved on to another batch while it was being stopped and the
re-offer's mark could not be written; only the block goes with the mark. NOTHING tells an
unjudged batch again by
itself, so a house that judges nothing cannot loop: the block is written once per batch
(the mark is closed or over by then), and the user's `kb ship <id> reoffer`, once the user has unblocked
the card, is the one way those items are offered again ("A re-offer", above).

Only a RE-OFFERED batch is settled this way (c-654 review). A normal batch's house is kept
two hours after its turn ends precisely so that a later turn can finish the judging: a
house at shipping ends a turn to ask the user something, or while a background job of its own
runs, and nothing nudges a house at a `Stop` there (`Board.stop_check` owns one rule, at
building). Blocking the card at that `Stop` would hand the user a batch its house was still on.
What a normal batch left unjudged shows as the pane's "judging N", and the user's
`kb ship <id> reoffer` offers it again once that batch's turn has ended.

**A batch due right behind a re-offered turn does not skip this** (c-666, "A batch due
behind a re-offer", above): the watcher, before it tells that batch, runs this step's own
settlement for that one card (`shipidle.before_batch`, `settle_reoffered`) on a strict
listing, so the close, the count and the block above happen first. A refused close is
decided by its kind: a job of the house's own or a terminal ends the re-offer with a note
stating that fact (`shipidle.end_unclosed`: `done_at`, no stop, no block); a row with no
process is the gone case; a failed stop or a failed listing settles and tells nothing on
that pass; a house found working is left to its turn. This step then finds the mark
settled, and a house the watcher closed is in this step's skip set for that pass.

All three check the house again on a fresh listing right before the stop, under the card's lock (`idleclose.close_here`) (`idleclose.not_idle`:
not working, no job of its own, not in a terminal, no voice hold). The log
line says `idle_ended=N` and `idle_closed=N`. The rule (a-72): merge to done
ends the card's idle house, and a shipping house idle over 2 h is stopped; the next comment
batch resumes it with its full conversation; never a working house.

## What the drain never does

- It never ends a live session that is doing something. `claude stop` is called on a human
  tap (the deck's Stop button and Close idle house, c-607; Approve outcome, or Adopt on a
  tier proposal, on the card's own finished house once it is done, c-621), by a resume on the one session
  it has just superseded, and by voice when a conversation starts, which is the same thing
  again: the conversation continues in that transcript. Three ends of an idle house are the
  drain's own ("Idle houses at shipping and after a merge", below): two decided with the user on
  ask a-72, a merged card's idle house and a shipping house idle over two hours, which its
  next batch resumes; and one on the user's explicit word (c-651), a shipping house whose
  re-offered batch's turn has ended, idle from then, which its next batch
  resumes. Besides those, the one case of its own is Bosun's wake with the user's answer to an ask ("The user's answers
  to Bosun: the wake", above): an idle Bosun is stopped and at once woken in the SAME
  session, the answer its prompt, decided with the user on c-521 (the user's D2). Never on a session
  that is doing something.
- It never respawns or escalates on a timer. Its clocks are its own poll interval, the
  backlog rule's date, a-72's two hours for an idle shipping house (measured from that
  house's own Stop, above), and `idle_resume_minutes`, which paces the one thing it does put
  back on a clock: a house whose turn ended with no `Stop` at all, three times and then a
  block. It never nudges a house that is working, and never one that ended its turn.
- It never reads a terminal, a pane or a log to decide anything. `claude logs` is read only
  to fill in a block reason nobody else supplied.
- It never touches a card at `review` or at an open plan gate.
- A pass of its own never resumes, wakes or starts a house on a card Bosun builds
  (`derived.bosun`, c-647), and that rule stops nothing: a session live there is left
  running. The user's taps and a rotation that was asked for still reach it ("The pass", step 3).
- It never pushes, posts or merges for a shipping card: it looks, and tells the house.
- It never kills by pattern. There is no kill path in Keel but `claude stop <id>` and,
  after it, the background shells that stop left behind, each by the pid the harness
  recorded and only once its start time proves it is still that shell (`keel/housejobs.py`,
  [houses](20-houses.md)).

## Harness facts that cost real time

All recorded from real probes, not assumed. The details are in
`tests/fixtures/harness/README.md`, `<install>/history/tests/live_house.md` and `<install>/history/tests/live_work_card.md`;
the tests run against those recordings, never a live session.

- `claude --bg` manages the session id itself. Never pass `--session-id`. It prints
  `backgrounded · <8-hex short id> · <name>`, and the short id is the first eight
  characters of the uuid `claude agents --json` reports.
- `claude --resume <uuid> --bg` continues the conversation but mints a NEW session uuid.
  The card's `session_id` follows the newest one.
- `--disallowed-tools`, `--add-dir` and `--tools` are variadic and will swallow a trailing
  positional. **The prompt goes before them.** A house that came up at an empty prompt cost
  one live run to find.
- `claude agents`, `logs` and `stop` see only the sessions of the `CLAUDE_CONFIG_DIR` they
  run under.
- The machine-default profile must be reached with `CLAUDE_CONFIG_DIR` **unset**: the
  keychain credential entry is keyed by the variable's setting, so a house launched with it
  set to the default path saw "Not logged in" while a plain shell was logged in.
- The per-config-dir background daemon pre-spawns spare processes and keeps the
  environment it was started with. After a login change, retire it by pid (never by
  pattern) before resuming, and put the per-card environment in the settings file's `env`
  block rather than the process environment.
- The `Stop` hook fires at every turn end and its `block` answer makes the session
  continue. `SessionEnd` fires when the process ends, including on `claude stop`. A stopped
  session disappears from `agents()` unless `--all` is passed. Every hook payload carries
  `transcript_path`, and a Stop payload carries `last_assistant_message`.
- A finished house stays a live process (`idle/done`) after its card is done. Ending it is
  a deck action, not the drain's: a done card whose session is still listed keeps its house
  row, so the pane draws Logs and Stop session (c-600, where the merge, not a tap, makes a
  work card done); it holds no slot and is not a Now tile.
- `agents --json` has a `state` of `blocked` meaning idle with nothing to do (a session
  waiting for input), distinct from `done`. The drain does not read `state`: the Stop hook
  is the primary signal and the row's presence is the cross-check.

## Where it lives

- `keel/drain.py`: the role, the claim, the start, the reconcile, and the quiet-house rule
  (`idle_stuck`, `resume_quiet`), which the deck reads too, with its login step
  (`quiet_login`, `login_upkeep`).
- `keel/login.py`: whether a space's login works: the words, the probe, `state/login.json`.
- `keel/housejobs.py`: an idle house's background jobs, read from the harness's job record
  (`jobs_upkeep` notes them).
- `keel/loginhold.py`: the drain's hold on a card for its space's login, and the comeback.
- `keel/logins.py`: the Logins list: every credential's row, its marks, its checks, `keel logins`.
- `keel/loginprobe.py`: the cheap check per kind of credential, and each one-liner.
- `keel/loginask.py`: the login ask, one per red episode of a row.
- `keel/board.py`: `open_board`, and `local_board`, which opens the file here with the `[keel]` switches and card defaults; every
  local Board in the CLI and the deck (its state, its POST paths, the board inbox) comes
  from it, since a Board opened bare has builder mode, the merge queue, rotation and
  `after=a,b` all off (c-591 review).
- `keel/kick.py`: the kick (c-598): the drain's inbox (`state/drain.sock`) and its thread (`Listener`, c-608), `kb`'s kick after
  a relay, and the Stop hook's kick for a held tap (`kick.host` kicks this machine's drain only).
- `keel/tellhouse.py`: a tap told to an idle house in its own session, or an exited one
  resumed (c-598).
- `keel/livestrip.py`: the live strip's facts (`facts_for`), which the deck's `Watcher` reads
  from this machine's houses while a stream is open.
- `keel/where.py`: whether a card can start here (its repos on disk, or scaffoldable), and the
  deck's `waiting` line.
- `keel/harness.py`: every `claude` invocation.
- `keel/machine.py`: this machine's available memory, its process table, and renice.
- `keel/shipping.py`: the pull request watcher's upkeep step: which cards, the look, the
  merge and the decline, the worktrees' own facts (`local_facts`), the batch told (`deliver`).
- `keel/teardown.py`: the teardown step: which cards, the building spell, the adapter's
  `ship <id> down`, the note.
- `keel/shipwatch.py`: the watcher's rules as pure functions: the cadence, the fold, the
  debounce, the batch.
- `keel/shipround.py`: a batch's words: the items, the adapter's method (`ship <id>
  method`), and Keel's protocol (`kb verdict`, `keel check`, never push).
- `keel/shipreplies.py`: the standing batch: a verdict's shape (`check`), the rows the deck
  draws, and the replies the user's Ship posts (`kept`, `ship_answer`).
- `keel/shipcheck.py`: what the user's Ship checks at publish time: a worktree its pull request's
  branch has left behind (refused, c-653), nothing
  to ship (refused), the house in a turn or commits no receipt covers (held, unless
  `anyway`).
- `keel/shipstep.py`: a worktree its pull request's branch has left behind (c-653): the
  commands that bring it in line by hand, worked out read-only, or why there are none.
- `keel/shipupgrade.py` and `bin/keel-shipping-upgrade`: the one-time carry from the
  review-round model (see "Deploying the living house" below).
- `state/logs/drain.log`: one line per pass, and the source of the deck's drain pill.
- the install's `config.toml`: `houses_max`, `poll_seconds`, `drain_paused`, `host` (this machine's name,
  which a claim and a relay carry), and the limits above.

## How to change it

The drain is small on purpose. Before adding a rule, check whether it is a fact the
harness already reports; if it is not, Keel does not get to act on it. A change to the
start or reconcile order changes what `tests/test_drain.py` asserts, and this page's "The
pass" section is the contract those tests hold to.
