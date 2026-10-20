# Segments and fetch

A segment is a small, additive, self-contained thing that gathers data on a schedule and
shows it: a daybook, a music library, a spend tracker, a machine's status. Each is a
directory with a `fetch.py`, a `data/` directory, an optional static `app/`, and a
`summary.json` the deck reads. A segment cannot break the agent, which is why the
boundary is static files only.

The **fetch role** runs those fetchers and turns what a segment asks for into a card.

## The two tiers

`keel fetch` has exactly two tiers, and one more thing a pass does that is not about
segments: it files the recurring cards that are due (below).

### Fetchers

`once(...)` runs every `<segments_dir>/*/fetch.py` in sorted order, with the working
directory at the segment, under a per-segment lock directory.

The lock protocol is the older system's, kept verbatim, and sharing the path is what makes
coexistence safe while both systems exist: `mkdir` is the atomic take; a lock whose owner
is dead, or that is older than an hour, is cleared with `rmdir` (never a recursive
delete); a lock with no pid file yet is treated as held. A held lock is reported as
`skipped`, and a lock directory that cannot be created at all is `unusable` and reported
as that, never mistaken for busy.

The interpreter is the venv beside the segments tree when it runs, tested by executing it,
else the code checkout's `.venv` (c-742: on an install the segments tree is the install's
and the venv built from `etc/segment-requirements.txt` is still the checkout's, so without
this a fetcher that reads PDFs ran under a bare `python3`), else `python3`. One failing fetcher (a non-zero exit, or 600 seconds without finishing)
never stops the others. Each segment gets one line in `state/logs/fetch.log`.

Every run of a fetcher that got as far as running (`ok` or `failed`) leaves
`data/.last-fetch`: when, which host, the state, and when the last good run was
(`fetch.stamp` in `keel/fetch.py`). That stamp is what `keel doctor` reads (below).

`changed_only` runs only a segment whose inputs moved: a file in `data/inbox/`, or
anything outside `data/` and `__pycache__` newer than `summary.json`. No summary yet
counts as changed.

### Asks

A segment that wants something done writes an ask. `asks(...)` turns them into cards.

Each segment with a `worker.md` and files matching `data/asks/ask-*.json` gets **one
autonomous errand card per segment per pass**, unless its daily cap is spent or its
`worker.md` is bad. A bad `worker.md` (no known space, or a non-integer cap or timeout)
fails closed: logged, nothing spent.

**The asks move into `data/asks/taken/` BEFORE the card exists**, so each is consumed
exactly once even if the house dies.

The card: the space from `worker.md`, no repo, `assigned`, titled `<segment>: <n> asks`,
with `plan_ref` the segment's `worker.md` (so `review` needs only an output),
`options.tools` the worker's tool list, `options.segment`, `options.asks` (the file
names), `options.add_dirs` naming the segment directory, and `options.drop`, the inbox
file the house must write.

The brief is the `worker.md` body, then this run: the taken ask **paths** (paths, not
contents, because an ask carries attachments a session with `Read` opens itself), the drop
path and its shape, the rules (write only the drop, never an ask, no commands, no
network), and the finish, which is the file and no command at all.

From there it is an ordinary card. The drain starts it `--restricted` with the worker's
tools and the segment as an `--add-dir`, and the next fetch folds the drop in and closes
the card. Every ask goes into the batch card; there is no live lane.

### The fold is its approval

Autonomy decides only the plan gate, so an ask card still reaches `review` with an outcome
gate open. That gate is empty. The fetcher folds the drop into the segment's own data
before anyone looks at the card, so by the time it appears under "needs you" there is
nothing left to decide: a card would sit there with the day's briefing already on
the page, one of those every morning (c-270).

So the fold is the approval. `close_folded` runs at the end of every fetch pass, over every
card at `review` that carries an `options.drop`, and reads the disk rather than the
fetcher's output, because where the file ends up is the only thing every segment's fold
agrees on:

- the drop is in `data/inbox-applied/`: the fold took it. The card is staged `done` by
  `fetch`, with the note "folded by the fetcher, so the outcome gate was already met".
- the drop is still in `data/inbox/` and that segment's fetcher has just run and exited
  `ok`: the fold ran and would not take it, because a successful fold always empties the
  inbox. This is a refusal. The card stays at `review` and is told why, once.
- the drop is in neither: the fetcher took it out of the inbox without applying it. Also a
  refusal, same treatment.
- the drop is still in `data/inbox/` after a fetcher that failed or was skipped: not yet.
  Nothing is written and the next pass looks again.

Reading the disk rather than a fresh fold is also what closes a card whose drop was folded
BEFORE any of this existed. There is no re-drop coming for one of those, so a rule keyed on
"a fold that just happened" would leave it at `review` forever.

A refused drop is the one case that deserves a look, which is why it keeps its gate. The
note is written once: the check runs every sixty seconds, and a note per pass would bury
the card's own history under one repeated sentence.

### The finishing step never needs a tool

**A card with `options.drop` is filed by its Stop hook, not by its house.** When the turn
of a card at `building` ends, `kb stop-check` reads the drop: if the file is there, is not
empty and parses as JSON (what the fold itself checks before reading one), the hook stages
the card `review` with the drop as `output_ref`, notes that it filed it, and does not
nudge. If the drop is not there yet the nudge names the FILE and no command.

The rule exists because the tool set and the brief disagreed. The daybook's `worker.md`
gives its house `tools: Read,Write`, with no `Bash` at all, and the brief used to end by
asking it for `kb stage $KEEL_CARD review --output <drop>`. Such a house writes its
drop correctly (the fetcher folds it), cannot run the command, is nudged for it
and blocks (c-270). A finishing step a confined house cannot perform is not a finishing step, so
the drop on disk is the finish and Keel does the filing. The turn-end hook's record check
skips an ask card for the same reason: its record is the drop.

`worker.md`'s `timeout` is validated but never enforced. Nothing automatic ends a live
session.

## Recurring cards

Work repeated on a schedule, such as a quarterly review of a checklist. Each is a `[recurring.<key>]` table in the install's `config.toml`: `every_days`, and the card to file
(`space`, `title`, `brief`, optionally `repo`, `autonomy`, `model`). A bad table (an
unknown key or space, days that are not a whole number of at least 1, no title) is a
`ConfigError` at load.

**The board is the whole memory.** Every card filed for a key carries
`options.recurring = <key>`, and `keel/recurring.py` decides from those cards alone: due
when none carrying the key is open and the newest reached `done` at least `every_days`
ago, or when no card has ever carried it. There is no schedule file and no last-run stamp.
So a pass every minute files each at most once (the card it filed is open, and an open
card holds the next), and the clock starts when the user closes the last one, however late it
ran. A due card is filed at `assigned`, as `fetch`, and logged as
`recurring <key>: <id> filed`.

## What each segment needs

Every fetcher runs on this machine, under the one fetch role. The inventory, read from each
`fetch.py` on 2026-09-20 (the `oci` row added since):

| Segment | Needs |
|---|---|
| `cloud-spend` | `data/usage.jsonl` (written by the voice gateway as it speaks) and the Google key for its daily identity probe: the Mac's keychain item or, on Linux, the one 0600 file `keel voice key set` writes, which the fetcher reads by name |
| `daybook` | RSS over the network, nothing else |
| `fathom` | its own journal drops, which the deck's app writes, and a coach session's transcript found under the config dir its status names (`~`-relative) |
| `instamart` | bills already on disk: `data/raw/` from the pull (a personal session with the mail connector) and PDFs uploaded through the app |
| `oci` | the grabber's tree, `~/oci-always-free`, and `launchctl` for its agent |

**A segment that stops updating says so.** `keel doctor` answers for every segment
(`fetch.staleness`): one with data and no good fetch in three hours (`fetch.STALE_SECONDS`),
or none recorded at all, is a problem line (`segment oci: last good fetch 4h ago; it has
stopped updating`). A segment with no data at all has never run and is not a problem.

**A fetch role that is not running says so** (c-742), since a segment that has never run
is exactly what the line above stays quiet about. On an install the doctor has a `fetch`
line, `running as pid N` or `NOT RUNNING`, read off this user's processes
(`drainprobe.fetching`), and with segments installed and no role running it is a problem:
`fetch: nothing runs the fetch role, so 2 installed segments (daybook, oci) never refresh:
`shipyard service install fetch` (or `shipyard fetch` by hand)`. `shipyard service status`
says the same under the fetch service's line.

**Recurring cards are filed by the fetch role** on every full pass, from the board alone
(above).

## The loop

`keel fetch` (the role) runs every fetcher on start and then hourly; every 60 seconds in
between it runs the changed-only fetch, then the asks, then the recurring cards. A pass's
exception is logged and never leaves the loop. `keel fetch --once` is one full pass and
prints `fetch: ok=N failed=N skipped=N unusable=N cards=N`, then a line per recurring card
it filed. A run narrowed to one segment files no recurring card.

**Who runs it.** On an install the role is a service of its own, `dev.shipyard.fetch`
(`keel run --roles fetch`, [install](88-install.md), c-742), beside the deck and the drain;
the old engine ran it as a thread of its one process (`keel run --roles drain,serve,fetch`).
An install with no services runs `shipyard fetch` by hand. Until c-742 an install ran no
fetch role at all, which is the first thing to check when no segment updates:
`shipyard service status` and the doctor both say so (below).

**One fetch role per install, held two ways** (review r1.F3). Fetchers were always safe
under two roles, each takes its segment's lock. Filing was not: a recurring key is read as
due and then its card is created, a segment's asks are listed and then moved one by one,
and two roles interleaved there filed a recurring card twice and split one segment's asks
over two errand cards. So what a pass files, it files under one lock
(`fetchloop.file_cards`, the lock `.fetch-.filing.lock` in `fetch_lock_dir`, the fetchers'
own protocol): a pass that finds it held files nothing and logs `filing skipped: another
fetch role is filing`; `keel fetch --once` then also says on its own output that the fetchers ran and no card was filed, and exits 1, since `cards=0` alone reads as nothing to file (r2.F3). And a second role is not started in the first place:
`shipyard service install` and `start` refuse the fetch service, and the drain's bring-up
holds it back, while `drainprobe.fetch_pids` lists another process running the role for
this install (`appservices.fetch_held`), each naming the pid and `kill <pid>`. The
service's own process is not another, and neither is a loop narrowed to one segment
(`fetch --segment x`, r2.F4): it leaves the other segments unfetched and files no recurring
card, so it holds nothing back and the doctor still names the segments nothing fetches.

**It follows its code and its config itself** (`fetchloop.follow_moves`). A process of its own
has no drain beside it to restart it, so between passes, never during one, it compares the
checkout's head and the config file with what it started on (`restart.stamp`,
`restart.moved`) and execs onto a move: a deploy, a `[recurring.<key>]` table added, a
`segments_dir` changed. A config that does not load is said once in `fetch.log` and the
running one kept. Where any other role shares the process the role's own restart is off
(`cli.role_run`, r1.F5): beside the drain or the deck the process may hold a conversation or a call an exec would cut, and their restart, which waits for those, is the whole process's. Every start is a full pass.

### A first pass after a long gap

A role that starts where none ran for weeks files cards nobody watched it decide. It files
few, and says which first:

- **Each recurring card at most once.** A key whose last card closed 400 days ago, with
  `every_days = 7`, is due once, not 57 times: the card filed is open, and an open card
  holds the next (above). A key no card has carried is filed once.
- **One errand card per segment**, however many asks waited: a pass batches a segment's
  pending asks into one card and moves them to `taken/` first, so the next pass has none.
  A segment's `daily_cap` still applies.
- **It says so before it files.** `keel fetch --preview` (`keel/fetchpreview.py`) prints
  what a full pass started now would file and exits: the fetchers that would run, a line
  per segment with waiting asks (`asks daybook: 3 asks, one card in personal`, or why none:
  the cap, a bad `worker.md`), a line per recurring key (`recurring weekly: one card in
  personal, "Weekly review" (the last one closed 400 days ago)`, or `no card (next on
  2027-11-20)`), and the count. It reads the board through a read-only connection, decides
  with the functions the pass uses (`fetch.read_worker`, `recurring.due`), runs no fetcher
  and writes nothing, so it is safe on a live install. It cannot count an ask a fetcher
  writes during the pass, and its last line says so. The role logs the same lines to
  `fetch.log`, as `first pass: ...`, before the first pass of every start
  (`fetchloop.say_first_pass`).

## In the deck

The state document carries each segment's `summary.json`, whether it has an `app/`, and
its URL. **A segment that has a `fetch.py` and no `summary.json` yet is listed too**
(`deckstate.segment_entry`, c-742), with `fetched: false`, no tiles, and `fetch_said`, the
page's words for it: "not fetched yet", or "not fetched yet: its fetcher failed
(state/logs/fetch.log says why)" when its one recorded run failed (`data/.last-fetch`). The
page draws its card with its name and those words, the Now page's segments row and `keel
deck segments` say the same, and readiness counts it as installed, so the Segments page
never says "No segment is installed" over a segments folder that holds one. A directory
with neither a summary nor a fetcher is still not listed.
The Segments route draws one card per segment; `GET /segments/<name>/app/...`
serves the segment's own app, with path traversal refused. A segment app is static files
and nothing else, so it can be written by anyone and reviewed by reading it. Its shell
(`.html`) is `no-store` and hands out the deck's cookie; every other file follows the deck's
own app file rule (c-549): gzipped when it is text (`serve.SEGMENT_ZIPPED`), an ETag of its
mtime and size, and `no-cache`, so a second open is a 304 per file and a deploy shows at once.

### What the deck serves for a segment, and what it accepts

An app that can only read is half of a segment. The three apps were written against the
old dashboard's routes, they are static files nobody is going to rewrite, and at cutover
the deck served the app and none of the rest, so every one of them was an empty shell:
`/segments/daybook/app/` answered 200 while `/segments/daybook/data/daybook.json` fell
through to the lavish proxy and answered 503, with the whole briefing already on disk.
`keel/segments.py` is the rest of that contract, kept identical to the old one on purpose.

| Route | What it does |
|---|---|
| `GET /segments/<name>/data/<file>` | one data file, from the segment's `data/`, never sniffed, and sandboxed when it is HTML or SVG (`artifacts.served_headers`: its fetcher wrote it). Daybook reads `daybook.json`; Fathom reads `index.json`, `schedule.json`, `blockers.json`, `packs.json`, `docs.json`, `live.json` and one `note-<id>.json` per card; Instamart reads `bills.json` |
| `GET /segments/<name>/summary.json` | the segment's own summary, which the app reads for its header |
| `GET /segments/<name>/inbox` | `{ok, pending: [{name, bytes, uploadedAt}], count}`. Instamart's app reads `pending` to say "waiting" honestly: its own data file only changes when the fetcher runs, so without this an upload looks like it vanished |
| `POST /segments/<name>/decisions` | one journal drop into `data/inbox/` |
| `POST /segments/<name>/inbox` | one file into `inbox/` at the segment root |

**The read is narrow on purpose.** The name must be one plain component matching
`[\w.-]+`, it may not be a dotfile, it may not be `inbox`, `inbox-applied`, `asks` or
`taken` (the segment's own working directories, not its published data), it must resolve
inside the directory it was looked for in, and the deck's credential denylist applies, the
same one the artifact route uses. `Cache-Control: no-store`, the content type from the
suffix, 404 when it is missing. **The whole `/segments/` prefix is the deck's**: a path
under it that matches no route is a 404 rather than the lavish proxy's 503.

**A write is a drop, never a change.** Neither POST knows what a decision MEANS. Each
validates the envelope, writes the file under a name generated by the server, and stops;
the segment's own `fetch.py` folds it in on its next pass and is the only thing that ever
interprets it. Both are refused unless they came from the deck's own page: `Sec-Fetch-Site`
must be `same-origin` or `none`, and an `Origin` must match the `Host` the browser
addressed (never an inbound `X-Forwarded-Host`, which is a client's claim). A request with
neither header is a non-browser client on loopback or the tailnet and is allowed, which is
what keeps curl and the selftests working. A GET needs no check.

| | decisions | inbox |
|---|---|---|
| Content type | `application/json`, or 415 | `application/pdf`, `image/png` or `image/jpeg`, or 415, and the file's own magic bytes must agree or 415 again |
| Size cap | 1 MB, or 413 | 10 MB, or 413 |
| Pending cap | 200 journals, or 429 | 200 files, or 429 |
| Shape | `{"entries": [{"k", "v", "t"}, ...]}`, non-empty, at most 20000 entries, every entry an object with a non-blank `k` and `t`, or 400 with the reason | none, the body is the file |
| Written as | `data/inbox/<stamp>-<fingerprint>-decisions.json` | `inbox/<stamp>-<fingerprint>-<hint>.<ext>` |
| Answers | `{ok, stored, entries, duplicate, pending}` | `{ok, stored, bytes, duplicate, pending}` |

The name is the server's, always. The stamp is UTC, the fingerprint is the first eight hex
of the body's sha256, and an upload's hint is the client's file name reduced to its
basename, stripped to `A-Za-z0-9._-` and truncated, with the extension taken from the
content-type table rather than the hint, so there is no separator left to traverse with.
The fingerprint is also the de-duplication: a phone that posts, times out after the write
landed, and retries is answered `duplicate: true` with the name the first copy got, rather
than filing a second one. A journal is matched against what is pending AND what has already
been folded into `data/inbox-applied/`; an upload against what is pending. Every write goes
to `<name>.part` and is moved into place, so a fetcher running mid-post never reads half a
journal and takes it as the whole of one.

**Two inboxes, and the difference is not cosmetic.** A decisions journal lands in
`data/inbox/`, which is the fold's door. An uploaded file lands in `inbox/` at the segment
root, which is where Instamart's fetcher reads invoices from. `changed_only` picks both up
inside a minute without a rule of its own: the first through `inbox_has_work`, the second
through `sources_changed`, since `inbox/` sits outside `data/`.

**One root.** The deck looks for a segment in the repo's own `segments/` first and in
`segments_dir` second (`Config.segment_roots`, the first root that has the name wins),
and since `segments_dir` is `~/keel/segments` those are the same path, de-duplicated to
one. The two-root shape is kept rather than collapsed in code, because they differ again
whenever `segments_dir` points elsewhere: a test config, or a `KEEL_HOME` aimed at a
worktree whose own `segments/` should win. The fetch role reads `segments_dir` alone, so
a segment only runs once it is in the tree that key names. On an install the order is
reversed: its own `segments_dir` wins over the checkout's `segments/`, since what `shipyard
import` copied there (each segment's code and its data, [import](87-import.md)) is what its
fetch role runs; a segment the install does not hold is still found in the checkout. An
imported copy does not follow a later change to the segment's code in the checkout.

## Where it lives

- `keel/fetch.py`: the role, both tiers, the lock protocol, `close_folded`, the run stamp
  (`stamp`, `read_stamp`, `stamp_age`) and `staleness`, which `keel doctor` reads.
- `keel/fetchloop.py`: the loop that runs the passes, with `follow_moves` and `say_first_pass`.
- `keel/fetchpreview.py`: what the next full pass would file, read and never written
  (`keel fetch --preview`, and the role's `first pass:` log lines).
- `keel/appservices.py`: the install's fetch service, `dev.shipyard.fetch`
  ([install](88-install.md)).
- `keel/drainprobe.py`: `fetching`, the processes running the role for this install.
- `keel/recurring.py` and `[recurring.<key>]` in the install's `config.toml`: the recurring cards.
- `tests/test_fetchloop.py`: two interleaved passes file each card once; a real fetcher that moves the code or the config mid-run, and the exec landing only after it, never beside another role.
- `tests/test_fetchpreview.py`: a first pass after a long gap files each recurring card and
  each segment's errand once and the next pass none; the preview names exactly those and
  writes nothing.
- `keel/segments.py`: the deck's segment tier, the data reads and the two drop routes.
- the install's `config.toml`: `segments_dir`, `fetch_lock_dir`.
- `segments/`: the repo's own segments tree, served ahead of `segments_dir`
  (`cloud-spend`, `daybook`, `fathom`, `instamart`, `oci`, `voice`, and
  `segments/README.md`, the contract for the inside of a segment).
- `.venv/`: the interpreter the fetchers run under, built from
  `etc/segment-requirements.txt`, beside the segments tree or in the code checkout
  (`fetch.interpreter`). `keel/` is stdlib only; this venv is the segments'.
- `state/logs/fetch.log`: one line per segment per pass.
- Each segment: `segment.md`, `fetch.py`, `data/`, `app/`, `summary.json`, and optionally
  `worker.md` with its space, `tools`, `daily_cap` and `timeout`.

## How to change it

- A new segment: `keel new segment <name>` writes `segment.md`, a `fetch.py` writing
  `summary.json` and its `test_fetch.py`, and checks the frontmatter with
  `keel/segmentspec.py`, which `keel doctor` also runs over every segment ([Extending
  Shipyard](63-extending.md)). Nothing in Keel changes. Give it an `app/` only if there is
  something to look at.
- A segment that needs an agent: add a `worker.md` naming the space, the tools and the
  daily cap. Keep the tool list as narrow as the job allows; it is the confinement.
- Before cutover, the old system's own hourly and minute jobs are still running against
  the same segments tree, and the shared lock directory is the whole reason that is safe.
  Keel's fetch role is therefore not scheduled until cutover: `keel install` writes the
  plist but loads it only with `--load`. See [cutover](80-cutover.md).
