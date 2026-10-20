# Start here

Keel is the engine that runs work for one person. A **card** is a unit of work. The
**drain** starts one **house** (a background Claude Code session) per card. The **deck**
is the web surface where the user answers the two gates. The **talker** is the session the user
speaks to from a phone. **Adapters** are the only place that knows about an employer.

That is the whole mental model. Everything else on this page is where to look.

## The one screen

```
    phone / desk ────► deck (keel serve) ────┐
    phone ───────────► talker session ───────┤
    voice gateway ───────────────────────────┼──► board.db  (the only state)
                                             │        ▲
    drain (keel drain) ──────────────────────┘        │
        └─► claude --bg, one house per card ──────────┘  (Stop / SessionEnd hooks)
                └─► packs/<name>  (worktree, brief, pr, publish)

    fetch (keel fetch) ──► segments/*/fetch.py ──► a segment ask becomes a card
```

One SQLite file, `state/board.db`, is the only state. Gates, "needs you", sessions and
worktrees are all derived from cards plus what `claude agents --json` reports. There is no
second store to keep in agreement.

## Five principles

1. **The harness is the runtime.** Claude Code owns sessions. `claude --bg` starts one,
   `claude agents --json` lists them, `claude logs` reads one, `claude stop` ends one,
   `claude --resume <id> --bg` continues one, and hooks report `Stop`, `Notification` and
   `SessionEnd`. Keel never scrapes a terminal, never types into one, never infers that a
   session is stuck from how long it has been quiet. If the harness cannot say it, Keel
   does not know it.
2. **One board is the only state.**
3. **Two gates, nothing between, nothing after.** Plan (attended cards only) and outcome.
4. **Mechanism over prose.** A rule for a house is a permission deny, a hook, a
   `--restricted` flag, or a command that does not exist in that session. The contract it
   reads explains; it does not enforce.
5. **Work and personal are two profiles of one engine, split by credentials only.** A
   space picks a `CLAUDE_CONFIG_DIR`, a set of repos and an adapter. Nothing else branches
   on it.

## What Keel does without

Keel is small on purpose. The harness reports what a session is doing, so Keel has no layer
that reads a terminal to guess it, and nothing built to make up for one.

| Instead of | Keel has |
|---|---|
| Rooms of agents with roles and a conductor | One card, one house. Subagents fan out inside a house; a big card splits into child cards at the plan gate ([cards and gates](10-cards-and-gates.md)) |
| A queue store, a dispatch ledger, a store per concern | One SQLite board. Needs-you is derived, not stored |
| Hosts, host assignment, caps per host | One `houses_max` per machine, and a drain liveness pill on the deck |
| A nudge ladder, wedge detection, respawn budgets | A `Stop` hook that pushes a house on twice, then blocks; the drain resumes an exited session once, then blocks ([the drain](30-drain.md)) |
| A long list of laws injected into every session | Five principles and a contract under 60 lines (`etc/house-contract.md`) |
| Dozens of card fields, many stages, several awaited channels | 16 card fields, 6 stages, gates derived from stage |
| Several dashboards | One deck, one navigation model across breakpoints ([the deck](40-deck.md)) |
| Its own tools to extend and promote itself | Keel is edited like any repo: a card, a branch, a review, a human merge |

## Where to look for what

| You want | Page |
|---|---|
| What a card is, its stages, the two gates, splitting a big one | [Cards and gates](10-cards-and-gates.md) |
| What a house is given, what it may do, how it ends | [Houses](20-houses.md) |
| What starts and recovers a house, and what it never does | [The drain](30-drain.md) |
| The routes, the state document, the actions, the artifacts | [The deck](40-deck.md) |
| The phone session and the voice gateway | [The talker and voice](50-talker-and-voice.md) |
| Worktrees, tracker stories, pull requests, the extra deck routes | [The work adapter](60-work-adapter.md) |
| Packs: what one is, its `pack.toml`, how a space names one, a pack someone shared, the rules for writing one | [Packs](62-packs.md) |
| Adding a pack, a segment or a deck view: `keel new`, the views manifest, the checks that hold each | [Extending Shipyard](63-extending.md) |
| How a space's work moves from a card's branch to where it ends: its flow, the moves the user makes on a card, changing it in Settings | [Flows](64-flows.md) |
| Whether a card's work builds: its checks, the builds that carry it, a failed step's log | [A card's CI](66-ci.md) |
| A shipping card's review: each round, what the house did with each comment, the user's replies and Ship | [A card's review comments](67-comments.md) |
| The demo sandbox: a Keel of its own with a code host and tracker on disk, and its seeded day | [The work adapter](60-work-adapter.md), "The sandbox adapter" |
| The demo video: one command from sandbox to MP4, the edit, the music and the evidence | [The demo video](65-demo.md) |
| Segments, the hourly fetch, asks becoming cards | [Segments and fetch](70-segments-and-fetch.md) |
| What is left of the two-machine era: the import path, the ignored keys | [Cutover](80-cutover.md) |
| The encrypted off-machine copy, its store, its four sets, the nightly pull and its alarms | [The backup](85-backup.md) |
| Keel back on a new machine from the store alone, by hand | [Restore](86-restore.md) |
| Bringing an old Keel's snapshot into an install: `shipyard import`, the path rewrite, what it blocks, the verify | [Import](87-import.md) |
| Setting Shipyard up on a new machine: `shipyard init`, its services, its own Claude login; `shipyard move-personal`, an owner's things moved from the checkout into the install | [Install](88-install.md) |
| Where Bosun's and the talker's memory and the user's profile live, seeded and read install first | [Bosun](96-bosun.md), "Where the memory lives" |
| A new install's repos and packs, added in the deck's Setup view; the CLAUDE.md tiers; the config writer and its backups | [Onboarding](89-onboarding.md) |
| Bosun: its session, its memory, builder mode, its repairs, the /console page, and Harbor's tools for it | [Bosun](96-bosun.md) |
| A word you do not recognise | [Glossary](99-glossary.md) |

## Where it lives

The checkout is the repo. Python 3.14, standard library only, no
pip dependencies, tests are `unittest` and run with `make test`. `state/` is gitignored and
holds `board.db`, `cards/<id>/`, `logs/`, `worktrees/` and `human.token`.

### The name, and the files a stranger reads first (c-699)

The product is **Shipyard**; the engine is **Keel**. `keel` is the package, `shipyard`,
`keel` and `kb` are the commands, and a session's variables start with `KEEL_`: none of
those is renamed. The split in words follows who reads them:

- **What a user reads says Shipyard**: the deck (its title, its installed name in
  `app/manifest.json`, every string of `app/*.js`), the first run, the installer's checks,
  a stuck card's line, a landing's refusal, a setting's help, a config warning, and the
  shipped packs' own text for the user (a manifest's description and fixes, a pull
  request's body, a Ship refusal). `tests/test_product_name.py` holds the deck to it, with
  a table of the two literals that say Keel on purpose (the chip of a card on the engine's
  own repo), and holds the packs that ship (`packs/sandbox/`, `packs/github/`, `packs/gitea/`): every
  string of a manifest and every string literal of the pack's code, with a table of the
  four sentences a house reads (the ending brief, the fence's refusals).
- **What a session is told keeps Keel**, beside the `keel` commands and `KEEL_*` variables
  it uses: the house contract, the briefs and prompts (`keel/prompts.py`), a refusal a
  house reads, Bosun's hooks. So do the Atlas and the code's own comments.
- **What a board already holds keeps the words it was written in.** A note, a block or
  an event stored before the name changed still says Keel, and the engine recognises
  some of its own sentences: to say a note once, and to find a block's fix. Each such
  comparison goes through `keel/oldwords.py` (`same`, `holds`), which accepts today's
  wording and the earlier one, so an upgrade neither repeats a note nor loses a fix.
  Three places read stored text this way: a landing refused for a changed repo file
  (`stuckcards.FILE_CHANGED`), the once-only notes of `shipping.note_held_batch` (the
  idle step's failed stop among them), and the out-of-step sentence of
  `shipping.say_local`. A new sentence that code compares with stored text is compared
  there too, never with `==` or `in` alone.

At the root: `README.md` (what Shipyard is, what it needs, the install command, the first
run, where the docs are), `LICENSE` (Apache-2.0, the standard text; the
copyright line of its appendix stays the license's own template, for anyone who applies
the license to their work), `NOTICE` (the copyright holder, the owner's own choice, and the
third-party works the tree bundles) and `CONTRIBUTING.md` (the house rules that are true for anyone,
and how to run the tests).

`NOTICE` lists three works, each with its path, its license and whether it was changed:
highlight.js and elkjs under `app/vendor/` (unmodified), and the demo's music (re-encoded,
with its tags and cover picture removed, as `demo/music/CREDITS.md` records; the public
release leaves `demo/music/` out, and NOTICE says so). Mermaid's
entry left with the one owner's segment that carried it (c-722 landing B).
`tests/test_thirdparty.py` holds the list to the tree: every tracked file under a
`vendor/` directory, every minified script, every font and every sound must sit at or
under a path `NOTICE` names, every path and license file it names must exist, and it may
not call the works unmodified as a whole. A search of the tracked files for those kinds,
for license files and for third-party copyright headers found nothing beyond the four.

### The test fence

**A test may not touch this machine, and the suite no longer takes that on trust.**
`tests/fence.py` runs once, at the import of `tests/__init__.py`, before any test module is
imported, on every platform:

- **The environment is scrubbed.** Every `KEEL_*` variable the caller had is removed, and
  `HOME` and `XDG_CONFIG_HOME` point at a throwaway directory, so a test that forgets an
  argument resolves `~/keel/state` and `~/.claude` inside the throwaway rather than the
  live ones. A git author goes in the environment for the same reason: moving `HOME` takes
  `~/.gitconfig` with it, and production code under test does commit. Tests build their
  subprocess environments out of `os.environ`, so children inherit all of it. The
  environment as it was before the scrub is kept (`fence.caller_env`, read through
  `fence.caller()`) for the checks `make drift` runs as modules of this package, which
  must read the install the CALLER named (`tests/installdrift.py`, `tests/publiccheck.py`):
  read from the scrubbed one, the install half of `make drift` read no install at all and
  passed (c-733). A test never reads it; it hands its own environment in.
- **The machine's own programs are fenced off.** A directory first on `PATH` holds a
  refusing stand-in for `systemctl`, `launchctl`, `sudo`, `loginctl`, `iptables`,
  `apt-get` and `tailscale`. Each records its argv, its cwd and its parent and exits 97, so
  a call cannot succeed by accident and is recorded even where the caller swallows the
  error. `tests/__init__.py` adds `FenceCase` after every other test, so a run that reached
  for one of them fails with the lines; an `atexit` guard says the same for the entry
  points with no package to hook, which are a single module and the packs' suites. Each
  pack's suite is a directory discovery with no package, so each of its modules imports
  its own pack's `<pack>/tests/suitefence.py` instead (`packs/github/tests/suitefence.py`).

**A test that leaves a `Board` open fails** (`tests/boardleak.py`, installed beside the
fence). Every `Board` opened while a test runs is recorded with the line that opened it, and
one still open when the test ends is a failure of that test, naming the line; it is then
closed. Before this the collector closed them whenever it ran, and the `ResourceWarning`
landed in whichever test was running then: a test that compared what `kb` prints failed about
one run in four, and was made to strip warnings from what it compared, which hid the leak.
No test strips them now. `Board` is a context manager (`with Board(path)
as board:`), and the deck's server closes the board-stamp connection its deck keeps when it
closes (`serve.DeckServer`).

A test that legitimately needs one of these names supplies its own fake earlier on `PATH`
(a pack's own test of a scan job's `launchctl` does). The fence
exists because a house running this suite can otherwise rewrite a live service file
and run `sudo iptables` against the host firewall. `<install>/history/docs/decisions.md` (rows
F1 to F4) names the two leaks and `tests/fence.py` carries the full account.

### Running the tests

**The suite needs nothing of one owner's** (c-722). The tree carries none of it: no work
pack, none of the owner's segments, no talker memory, no profile, no owner's config (c-722
landing B; Bosun's old memory folder waits for the owner's own removal, and no test reads
it). A test that needs a pack with a capability writes one in its temp dir (a `ci` pack, a
`flow_pr` pack, a story-and-pull-request pack), a pack's own manifest is held by its own
suite, a check that reads the packs' drift terms skips when no pack in the tree carries
any, a test of the shipped config reads `etc/shipyard.example.toml`, and fixtures name
neutral repos (`api`, `web`) and tracker refs (`st-<n>`). The Atlas names what left the
tree where it lives now, `<install>/...`, and every backticked repo path it names exists
(`tests/test_atlas.py`, no exception).

**Where something lands, `make test` runs: the core suite and what the change reaches**
(c-544 decision G-5, narrowed by c-646). The planner's merges, Approve outcome and the merge
queue run `[tests]` from the config (`make test BASE={base}`, `{base}` the commit the merge
is built on) on the merged tree. A house runs `make test-changed` before it stages
review (`[house_tests]`, `BASE` its card's base; a work house runs a targeted test while it
builds and its one full container run in the pipeline, c-597), and the review stamp records
which suite that was (`keel/review/testrun.py`, below). **Every test, voice included, is
`make test-all`, run on demand and at every deploy**: the deploy is the gate that runs every
module (`[deploy_tests]`: the deploy suite includes voice), so what the narrower
runs leave out (an extended module reached only through a chain of imports) is caught there,
before main moves. It refuses a run that skipped voice, did not reach it, or chose its
modules, and runs no suite only on a tree a full run already proved: a landing whose run
fell back to every module, or `kb tested` after a green `make test-all`; a landing's narrow
`make test` records nothing ([the drain](30-drain.md)).

| Target | What it runs |
|---|---|
| `make test [BASE=main]` | the drift grep, then the core suite (`tests/core.txt`), every extended module that imports a changed file itself or is named for it, the packs' own suites (each `packs/<name>/tests`) when `packs/` changed or a file one of their tests imports did, the voice selftest when the change reaches it (`voice/`, a `bin/keel-voice*` script, a file the voice package or `bin/keel-voice-selftest` imports through any chain, `segments/voice/`, `<install>/segments/cloud-spend/`, a pack's `hearing.json`), and the Python 3.12 import check; every module (`make test-all`) when the selector cannot place a change |
| `make test-core` | the drift grep, then the core suite alone with the Python 3.12 import check: the fastest whole signal |
| `make test-all` | the drift grep, then every `tests/test_*.py` module across worker processes, with the packs' own suites (one job, `tests/packsuites.py`: each `packs/<name>/tests` in turn, then each of the install's own packs when `KEEL_CONFIG` names one, c-726 r1.F4), the voice selftest and the Python 3.12 import check running beside them as jobs; what every deploy runs (`[deploy_tests]`) |
| `make test-serial` | the same suites as `make test-all`, one after another in one process each, the way they ran before the parallel runner |
| `make test-changed [BASE=main]` | the drift grep, then only the modules the change since `BASE` can reach through any chain of imports, or every module when the selector cannot tell |
| `make test-again LOG=<red log>` | only what a red run's log names as failed, once: each failed test in its own child and each failed job whole (`tests/parallel.py --rerun`); what the deploy runs on red (c-526) |

**The core suite** is the one list `tests/core.txt` (c-646): the modules that guard Keel's
core promises, a comment above each group naming the promise. The board's rules and gates
and its stage moves; what the drain starts, resumes and refuses; the house fence; relays and
taps reaching houses; the landing; the deploy; and the suite's own guards (the Atlas test,
the fence, the leak check, the shipped config, the list's own check). Every other module is
extended, by default: nothing marks it, so a module is in exactly one place by
construction. `tests/suites.py` reads the list (`core_modules`, `extended_modules`), and
`tests/test_suites.py`, itself core, fails on a name that is no module or a name given
twice, and holds what `make test` takes. A new test is extended unless it guards a core
promise no core module covers yet (the a-78 test rule); moving one into core is a line in
the list.

**Why `make test` takes an extended module only by a direct import.** Through a chain,
nearly every module reaches nearly every other: `tests/helpers.py` imports the board and
the config, and lazy imports join about 150 of the 191 `keel/` modules into one component,
so a change to any `keel/*.py` reaches about 198 of the 216 modules through the chain. That
is right for `make test-changed`, which a house runs to iterate. For `make test` the core
suite runs whatever changed, so it adds only the extended modules whose own area changed: a
module that imports the changed file itself, or `tests/test_<name>.py` for `keel/<name>.py`,
or one that names the file. A change to `keel/sentences.py` runs the core suite and three
extended modules; to `keel/board.py`, the core suite and the 74 that import the board
themselves. The chain is covered by the deploy, which runs every module before main moves
(`make test-all`, above); no scheduled run covers it.

The c-646 audit (2026-10-05) measured every module once on this machine under load (8
workers, other builds running) and kept the numbers here. Before it the stdlib modules ran
4413 tests; 283 of those were the same tests run again, because five test classes that held
tests were subclassed to borrow their fixtures (`StopHookTest` alone ran 14 tests 18 times
over, through `test_review_delta`, `test_review_passes` and `test_review_handback`). Each
fixture now lives in a base class with no tests of its own (`StopHookCase`, `AskedCase`,
`RootsCase`, `MacHalfCase`, `PushCase`), and a second `ActorTest` in `tests/test_cli.py`
that had shadowed the first, so three of the actor rule's tests never ran, is
`ResolveActorTest`. Exact duplicates, wording and CSS pins and dead classes went too (the
c-646 commit message lists each with its reason). After it, 37 modules are core and 179
extended; `make test-core` ran 1000 tests in 32.5 s and `make test-all` 4120 tests in 99.4 s
(its stdlib batch; the adapters suite took 42.5 s beside it, and voice was skipped for want
of a venv in the worktree), against 4414 tests in 253 s for the full suite at c-622's
landing, where the voice selftest alone took 179 s.

**The order is longest first, by size on disk.** On the measured times, size order finishes
the core suite on 8 workers in 69 s, ordering by each module's measured time in 64 s, and
64 s is `tests/test_deploy.py` alone, the long pole whatever the order; a store of timings
would buy 5 s and be one more thing that has to agree with the tree, so the runner keeps
size.

`tests/parallel.py` is the runner: one child process per test module,
`min(cpu_count, 8)` at a time, longest first by size on disk, each child importing the
`tests` package first so the fence and the Board leak check are installed in it exactly as
in a serial run. Every child and every job runs with `PYTHON_COLORS=0` and `NO_COLOR=1`
(`parallel.plain`, c-553): a Claude Code background session sets `FORCE_COLOR`, and Python
3.14 would colour a child's traceback. Output comes back module by module in name order, then the failures, then
one `Ran N tests` line and `OK` or `FAILED`, as a serial discovery prints them. Each child
checks its own fence and the parent counts the fence as one test, failed if any child's
fence recorded a call. **A child counts only by its complete result record**, written in
one rename after its whole module ran and carrying how many tests it found and how many it
finished: whatever its exit status, a missing, partial or short record is an error named
after its module, because a test calling `os._exit(0)` ends its child with 0 and the rest of
the module unrun. `--job NAME=COMMAND` runs another whole suite beside the batch, in the
caller's unfenced environment as the Makefile would (`fence.caller_env`), and prints its
output after the summary. **A job counts only when it exits 0 and its last line matches its
`--done NAME=REGEX`** (unittest's `OK` for the adapters suite, the selftest's closing `ok:`
line or the skip note for voice, `py312: ok` or its skip note for the import check); every
job must name one, and the run fails otherwise. `--durations N` adds the slowest tests
and the slowest modules. `SERIAL` in that file names any module that cannot share the
machine, with the resource it shares; those run one at a time after the batch. It is empty:
every server a test starts binds port 0 and every path a test writes is under its own
temporary directory.

**Python 3.12 is checked too** (J-3). A machine may run Keel on its own
`/usr/bin/python3`, 3.12.3, and 3.14 evaluates annotations only when something reads them,
so a module naming a class in an annotation before the class exists imports on 3.14 and
raises NameError on 3.12. `tests/py312.py` (the `py312` job, `python3 -m tests.py312`)
imports every `keel/` module in a `python3.12` child, where every annotation is evaluated
when its `def` runs, compiles every Python script under `bin/`, and resolves every `keel`
name a script imports. With no `python3.12` on PATH it prints `py312: skipped` and a note
(Homebrew's `python@3.12` gives a Mac one). It runs after the fence, so the child's `~`
is the throwaway one. `make test` and `make test-core` run it every time; `make
test-changed` does not, unless it falls back to every module.

`tests/selector.py` is `make test-changed`, and with `--core` it is `make test`. The changed files are `git diff --name-only
BASE...HEAD` plus everything uncommitted and untracked, and each is placed by one rule,
printed beside it:

- a Python file under `keel/`, `voice/`, `packs/`, `tests/`, or a Python script in
  `bin/`: every test module that imports it through any chain (for `make test`, only one
  that imports it itself, unless the change is to a test module), from a static `ast`
  import graph of those trees, plus `tests/test_<name>.py` and any test naming the file;
- `app/`: the tests that read app files; a `bin/` script: the tests that name it;
  `etc/shipyard.example.toml`, the shipped config: `tests/test_config.py` and the tests
  naming it (the tree tracks no `keel.toml`, c-726 r1.F3);
  `tests/core.txt`: `tests/test_suites.py`;
  `docs/` and `etc/`: the guards and any test naming the file;
- anything under `packs/` also runs each pack's own suite, and anything under
  `voice/` or a `bin/keel-voice*` script runs the voice selftest, which nothing else does.
  When nothing does, the selector says so on a line of its own (`voice selftest: not run,
  ...`, its `VOICE_UNREACHED`), which is how a landing and a deploy tell a run that owed no
  voice from one that skipped it ([the drain](30-drain.md)).

The guards run every time: the drift grep, `tests/test_atlas.py`, and the fence in every
child. **The selector fails safe**: a changed file no rule places, a deleted Python module,
and any change to the suite's own machinery (`tests/__init__.py`, `tests/fence.py`,
`tests/helpers.py`, `tests/boardleak.py`, the runner, the selector, `tests/suites.py`, the
`Makefile`) run every module (`make test-all`), and it prints which file and why before
anything runs.

**What ran is recorded for the review stamp** (c-544). Every run of the selector, every
`make test-core` and every whole `make test-all` (`tests/parallel.py` with no modules named)
writes `keel-test-run.json` in the worktree's OWN git directory (`git rev-parse --git-path`): the
HEAD, whether the tree was clean, `targeted` or `core` (with its module count) or `full`
(with why), the exit code, and for `make test-all` whether the voice selftest ran and passed
(`voice`: its skip note exits 0 too, so a skip is `false`). `kb tested` reads it: it records a
tree only when some worktree of the repo holds a green `full` record, voice passing, at that
exact commit on a clean tree (`testrun.full_green`, c-646). It is never committed and goes with the worktree. When the reviewer or
verifier finishes, the stamp hook copies it onto `review-stamp.json` as `tests` if it was
taken at the stamped HEAD on a clean tree, else `{"kind": "none"}`, and `review.md` ends
with one line saying which ([houses](20-houses.md)).

**A test waits on a clock only where the clock is the thing proved.** The slow tests were
waits on real intervals: the stdlib's half-second `serve_forever` poll paid in every
server's teardown (`helpers.serve_in_background` polls at 0.05 s), a watchdog's grace
between TERM and KILL (`KEEL_BROWSER_HARD_GRACE_S`, `harness.GROUP_GRACE` patched), and the
deck's stream tick and sweep (`serve.STREAM_TICK`, `deckevents.SWEEP_SECONDS` patched, with
the listening window shortened so a silence is still proved over at least as many sweeps).
A wait that must not start before a fake is ready waits for the fake to say so: the
harness's group-kill tests count the turn budget from a file the fake touches once its trap,
child and pid file are in place (`gated_popen` in `tests/test_harness.py`), because under
load the budget ran out before bash had made the child the test is about. Each is an
interval the code reads at call time, so a test shortens it the way
`tests/test_drain.py` injects the drain's clock (`<install>/history/docs/decisions.md`, I7): it never sleeps
through what it can move.

`<install>/history/docs/plan.md` is why the system has this shape, `<install>/history/docs/decisions.md` is what was decided
and when, `docs/layout.md` is the binding module and data contract every builder follows,
and `docs/atlas/` is this, the source of truth for how it all works.

### The module map

Three launchers: `bin/keel` (the roles, `keel doctor`, `keel deck`, and the `talker`,
`voice` and `backup` verbs), `bin/kb` (the board CLI) and `bin/keel-turn-end` (the
turn-end half of a house's Stop hook). The voice gateway's scripts (`bin/keel-voice*`) sit beside them but run
on their own interpreter; [the talker and voice](50-talker-and-voice.md) lists them.
`bin/keel-backup` and `bin/keel-backup-selftest` are the backup tool and its proof, in bash
for the reason [the backup](85-backup.md) gives, and `bin/keel-backup-setup` is the wizard
that sets up its Google Drive store (eight stages). Restoring from the store is done by hand
([restore](86-restore.md)).

| Module | What it owns | Page |
|---|---|---|
| `keel/config.py` | the config loader, the resolved paths, the space table | this page |
| `keel/configpath.py` | which toml a process reads (`KEEL_CONFIG`, else the root's `config.toml`, else an older checkout's `keel.toml`, else the shipped example), and the toml a child or a service file is handed (`named`); stdlib only, the voice gateway imports it | this page |
| `keel/oldconfig.py` | the keys a two-machine config still carries (c-622): each dropped or carried, and named in `Config.warnings` | this page |
| `keel/board.py` | the store: schema, writes, stage refusals, approve, split, and `open_board`, the one way to open this machine's board | [cards](10-cards-and-gates.md) |
| `keel/views.py` | the `derived` block attached to every card read | [cards](10-cards-and-gates.md) |
| `keel/stacking.py` | a waiting card stacked on the card it waits for, or independent of it (c-718): the owner's `options.stack`, who may record it and where, `derived.stack` read off the parent's card, the branch a stacked card is taken against, the owner's Approve plan recording the plan's `stack` batch, and each slice's answer at the split | [cards](10-cards-and-gates.md) |
| `keel/tree.py` | the card tree: a tracking card's outline (steps, next, unblocks), assigning a whole tree, the queue and `kb next` | [cards](10-cards-and-gates.md) |
| `keel/cardspec.py` | the card defaults: the one resolver every create goes through, each field's provenance, the readback, the corrections, the option sheet | [cards](10-cards-and-gates.md) |
| `keel/models.py` | the model names `claude --model` is given, `KEEL_MODEL`, and Keel's own turns (`[models]`) | [cards](10-cards-and-gates.md) |
| `keel/sessionorigin.py` | the csr sidecar: a house's session declared to the session index, naming its card | [houses](20-houses.md) |
| `keel/cli.py` | one table of verbs, which argparse, the dispatch and `kb help` all read | [cards](10-cards-and-gates.md) |
| `keel/where.py` | whether a card can start here (its repos on disk, or scaffoldable: `startable_here`, `missing_repos`, `can_scaffold`) and the "Cannot start this" line the deck's `waiting` carries (`waiting_text`, `waiting`) | [the drain](30-drain.md) |
| `keel/importer.py` | the one-time fold of the old ledger into the board | [cutover](80-cutover.md) |
| `keel/harness.py` | the only place that runs the `claude` binary | [the drain](30-drain.md) |
| `keel/relay.py` | a message into a running session on this machine (`tell`, a one-shot `claude -p` through `harness.run`) and the check that it went (`relayed`, `RelayUnclear`); split out of harness.py (c-531) | [the drain](30-drain.md) |
| `keel/kick.py` | the kick (c-598): the drain's inbox socket and the thread that listens on it (c-608), `kb`'s kick after a verb that wrote a relay, and the Stop hook's kick for a tap held on a working house | [the drain](30-drain.md) |
| `keel/tellhouse.py` | the user's tap told to an idle house as a message into its own session (same id, same app link), an exited one resumed, a working one refused for its caller to hold (c-598) | [houses](20-houses.md) |
| `keel/logtrim.py` | keeps `state/logs` bounded: a log past 5 MB is copied to `<name>.1` and cut back in place to its tail; the drain calls it each pass | [the drain](30-drain.md) |
| `keel/machine.py` | what this machine says about itself: available memory, the process table, renice; the drain's limits read it | [the drain](30-drain.md) |
| `keel/afresh.py` | a house whose conversation the harness no longer holds (c-654): the three conditions a fresh start needs (no live process listed, the harness says gone, no `Stop` of that session on the board in 14 days), the block for the user when the board contradicts the harness (an unblock answers it) or a fresh house dies too, and the start itself | [houses](20-houses.md) |
| `keel/house.py` | brief assembly, the settings file, the worktree, launch and resume | [houses](20-houses.md) |
| `keel/merging.py` | Approve outcome on a personal repo card: tests, merge, clean up; `code_head` for the restart check | [cards and gates](10-cards-and-gates.md) |
| `keel/cardtitle.py` | a short title for a card filed from the user's own words, and a title cut at a word for a merge subject (c-729) | [onboarding](89-onboarding.md) |
| `keel/prompts.py` | every sentence Keel says to a house that is not the contract | [houses](20-houses.md) |
| `keel/planreview.py` | the plan format's `review` kind: the rules (C28 to C32) a review card's outcome is held to before the user's gate opens, and `items`, its findings read in either shape | [plans on the deck](47-plans.md) |
| `keel/planexcerpt.py` | a review finding's code, read from the worktree at HEAD when the page is drawn (four lines either side; a feature finding in its member's worktree) | [plans on the deck](47-plans.md) |
| `keel/planfinding.py` | the `finding` block: one review finding whole (severity, member, `at: path:line`, claim, evidence, verifier, suggestion, comment, choice) | [plans on the deck](47-plans.md) |
| `keel/planbrief.py` | the brief's plan section: with `plan_pages` on the format card, the lint, the board rule and Ask; off, the plan styles; and the record a new card starts with | [plans on the deck](47-plans.md) |
| `keel/planfacts.py` | what a card row and Attention say about a plan or outcome in the format: the document's counts and lint, cached per file stamp and read where the file is, and the user's round off the events | [plans on the deck](47-plans.md) |
| `keel/planinstall.py` | `bin/keel-plan-install`: a converted plan and outcome put on a real card (boards pushed or reused, ids rewritten, linted, the old files kept, `plan_ref` moved, one note) | [plans on the deck](47-plans.md) |
| `keel/planoutcome.py` | C33: an outcome that ships a change embeds a board pushed after the user's plan approval and a numbered reading order under Why this shape; a board carried over from the plan is a warning and a tag on the page (c-602) | [plans on the deck](47-plans.md) |
| `keel/outcomeboards.py` | `bin/keel-outcome-boards [--card c-N] [--run]`: the C33 backfill, a board-only turn relayed to each house (not archived, not Bosun's) whose outcome is at review or shipping without boards drawn at the built head; prints what it would do unless `--run` (c-602) | [plans on the deck](47-plans.md) |
| `keel/plancard.py` | the plan format as one card, generated from the parser and the lint, embedded in the brief and in `docs/plan-format.md` | [plans on the deck](47-plans.md) |
| `keel/ending.py` | the turn-end hook: the record at the outcome gate, the discussion flag, the card's news | [houses](20-houses.md) |
| `keel/briefnews.py` | the brief's card block, and a briefed field changed since the house read it, told at its next Stop or resume | [houses](20-houses.md) |
| `keel/teardown.py` | a drain step: a card that left building has its own containers torn down through the adapter, once per building spell, its worktree kept | [the drain](30-drain.md) |
| `keel/shipping.py` | the pull request watcher, a drain step: the look, the merge and the decline, the worktrees' own facts, a batch told to the card's living house (c-600) | [the drain](30-drain.md) |
| `keel/stackwatch.py` | stacked cards, a drain step (c-718): a parent dropped blocks its card once; a parent landed aims the card's change at the base (the pack's `ship <id> restack`) and tells its idle house how to move the branch; a parent's branch that moved is told once per head. It stops, resumes and starts nothing | [the drain](30-drain.md) |
| `keel/shipwatch.py` | the watcher's rules as pure functions: how often to look, what is new, when a batch goes (the debounce) | [the drain](30-drain.md) |
| `keel/shipround.py` | a batch's words: the items, the adapter's method for judging review, and Keel's protocol (`kb verdict`, `keel check`, never push) | [the drain](30-drain.md) |
| `keel/shipauto.py` | automatic handling at shipping, one switch per kind (c-655): the space's two settings and the card's own options over them (`chosen`, `for_card`), where each waiting item waits (`settle`: the batch or `untold`), the cadence of a kind just turned on (`as_waiting`), what the deck counts for the user's hand-over (`handover`) and the verb's refusals in plain words (`plain`) | [the drain](30-drain.md) |
| `keel/shipreoffer.py` | a re-offer (c-651): `kb ship <id> reoffer [--rebase]`'s ask (the user's alone), the drain's fill of the review the house was never told, or was told and never judged (c-654) (and a rebase item, the base merged in, never a rebase), the batch marked, and its own turn found by the board's order of events, whose end stops the house | [the drain](30-drain.md) |
| `keel/shipsendback.py` | Send back at shipping (c-663): `kb ship <id> sendback`'s ask (the user's alone, `options.sendback`, one entry per send-back), the drain's fill of each as an item of the user's own kind (`his-<n>`) that no automatic-handling switch parks and that is due at once, an ordinary item of the batch from there (no hand-over mark, so nothing of it stops a house or blocks a card), and what the deck says still waits and why (`waiting`, `held`) | [the drain](30-drain.md) |
| `keel/shipreplies.py` | a shipping card's standing batch (c-600): a verdict's shape, the rows the deck draws, and the replies the user's Ship posts once | [cards and gates](10-cards-and-gates.md) |
| `keel/shipcheck.py` | the check of the user's Ship at publish time (c-600 review): a worktree its pull request's branch has left behind is refused (c-653), and so is nothing to ship; the house in a turn or commits no receipt covers hold it unless the user says `anyway` | [drain](30-drain.md) |
| `keel/shipstep.py` | A worktree its pull request's branch has left behind (c-653, behind or rewritten outside Keel): the exact commands that bring it in line by hand (a fast-forward; or a backup branch, then the replay of the card's own commits, or the move of the branch), worked out read-only, or why Keel can give none. Keel moves no branch | [cards and gates](10-cards-and-gates.md) |
| `keel/shipupgrade.py` | `bin/keel-shipping-upgrade [--run] [--deck <url>]`: the one-time carry of work cards from the review-round model to the living house, a dry run by default, never a session call | [drain](30-drain.md) |
| `keel/fixcheck.py` | `keel check <card>`: after a commit at shipping, a fix check, a full pass, or nothing, and the one receipt is the review stamp (c-600) | [houses](20-houses.md) |
| `keel/reviewcards.py` | the review fetcher, a drain step: one review card per pull request that needs the user, a notice for one that closed first, new commits flagged on a posted one | [the drain](30-drain.md) |
| `keel/reviewsettings.py` | the review fetcher's two settings, auto review and the review model: the config's values and the live override the deck's gear writes under `state/` (saving the key in Settings clears it, c-633) | [the drain](30-drain.md) |
| `keel/reviewround.py` | the user's Approve of a review card: the findings kept (the user's words for an edit) at their lines, the summary, the verdict and the ledger, handed to the adapter's `publish` | [cards and gates](10-cards-and-gates.md) |
| `keel/prsbackfill.py` | `bin/keel-prs-backfill [--dry-run]`: the one-time fill of `options.prs` from a card's own `options.pr`, for each card at review or shipping missing its primary repo's entry (c-584) | [cards and gates](10-cards-and-gates.md) |
| `keel/shipsync.py` | `bin/keel-shipping-sync [--dry-run]`: the user's open pull requests (the adapter's `ship mine`) matched to their cards, recorded as `options.prs`, and every card whose pull requests are all ready moved from done or review to shipping (SH-11) | [cards and gates](10-cards-and-gates.md) |
| `keel/console.py` | Bosun's session: `keel console` (status, memory, guard, and the verbs that reach the taps), its settings, `state/console.json`, the tap lock, the status the deck draws | [Bosun](96-bosun.md) |
| `keel/builder.py` | Bosun's builder (c-619, c-621): `[builder]` read (`superuser`, `repos`, `mode`), the repos Bosun builds and its clones of them, the live checkouts it keeps out of, the settings of its session (auto or bypass, the guard hook, the secret and push denies, the build allows), and why it may not start (a superuser on an install included) | [Bosun](96-bosun.md) |
| `keel/builderauto.py` | the builder's auto mode (c-621): the `autoMode` block its own settings carry (environment, hard_deny, soft_deny, allow) and the push deny rules | [Bosun](96-bosun.md) |
| `keel/tierdrafts.py` | what came back from Bosun (c-678): one row per CLAUDE.md of a space with its state (not started, drafting, ready, adopted) read from the tier and the draft card's stage, the draft's text and the lines Keel reads from it, and the verdict the first-run step is done by | [onboarding](89-onboarding.md) |
| `keel/repocommands.py` | a repo's commands put to work (c-678): the test command a landing runs (`[tests]`, else the adopted file's), the prepare command a fresh worktree and the merged tree get, the branch work lands on put out in Keel's copy at Adopt, and the sentence for a landing that runs no tests | [onboarding](89-onboarding.md) |
| `keel/landpush.py` | fetch before work and the Push after a landing, for a repo the install copied in a space with no pack (c-678): the fetch and fast-forward when a worktree is cut, what a landed card says about its push, the page's `land.push` and `land.push.check`, and the panel that keeping work on this computer is drawn from ([flows](64-flows.md), [onboarding](89-onboarding.md)) |
| `keel/browserinstall.py` | the first run's install of Keel's browser (c-678): Node.js 20 or newer, the one background download (`bin/keel-browser install`, detached from the deck), its progress read from the installer's own lines (c-757), and the sentence a download that stopped says ([onboarding](89-onboarding.md), "A browser for sessions") |
| `keel/backupsetup.py` | Back up turned on from the first run (c-678): a folder as the store, never inside the install, the config's `[backup]`, the tool's `init` for the keys, the two jobs loaded from the install's `services/`, the first copy started, the passphrase returned once; refused with no gpg ([backup](85-backup.md), "Turned on from the first run") |
| `keel/backupstatus.py` | what the Back up step shows (c-757): the first copy as it is observed (written, writing only while a run holds the lock, failed with the tool's reason, none), the proof with its real next day, only readings that are this install's (`[backup] since`, which the drain's watch reads too), and the step's verdict: done once a copy exists, and never Done over a row that says otherwise ([backup](85-backup.md), "Turned on from the first run") |
| `keel/oldwords.py` | a sentence the board holds in the earlier release's words (c-699): `same` and `holds` accept both wordings, for the code that recognises its own stored note or block |
| `keel/stuckcards.py` | the stuck states outside setup (c-678): a card's block read into what happened and its fix (a session that will not start, a refused landing by what refused it), the fixes that are the page's verbs, the drain's service restarted, and an unknown config key read, removed or renamed ([onboarding](89-onboarding.md), "The stuck states outside setup") |
| `keel/tierrecord.py` | which text of a tier file the user adopted or saved (c-678 review): the note Adopt and Save leave with the written text's digest, and whether a file is still that text, which is the only text `repocommands` runs a line from | [onboarding](89-onboarding.md) |
| `keel/repofile.py` | the lines Keel reads out of a repo's adopted CLAUDE.md (c-678): the prepare command, the test command, the branch work lands on and how to run the app, each by its opening words, with its line | [onboarding](89-onboarding.md) |
| `keel/cloneerrors.py` | a failed copy of a repo sorted into a kind (c-678): private on GitHub, private on another host, no such repo, an SSH address with no key, anything else; each with its sentence, git's own line and what the fix needs. Reads strings only | [onboarding](89-onboarding.md) |
| `keel/bosunhello.py` | whether the user has said anything in Bosun's session (c-678): the first run's Meet Bosun reads it from the transcripts of the sessions Bosun has had, a file at a time and only what was added | [onboarding](89-onboarding.md) |
| `keel/builderguard.py` | `bin/keel-builder-guard` (c-621): the builder's one fence, a PreToolUse hook refusing an edit inside a live checkout (the editing tools by realpath, failing closed; Bash as a speed bump), in auto and bypass alike | [Bosun](96-bosun.md) |
| `keel/consoletaps.py` | Bosun's three taps (start, stop, restart) and the stuck-row recovery they share, one at a time under the tap lock; split out of console.py (c-531), an authority path | [Bosun](96-bosun.md) |
| `keel/requests.py` | Bosun's requests: the `requests` table's reads and writes, `kb console` (ask, list, show, take, resolve, hook, gaps, and the asks' sub-verbs handed to `keel/asks.py`), `kb block --keel`, the drain's and doctor's sightings | [Bosun](96-bosun.md) |
| `keel/asks.py` | Bosun's asks: the `asks` table's reads and writes, `kb console` raise, asks, answer, withdraw, and the delivery lease (pending, claim, confirm, unclaim) the drain's wake and Bosun's hook take | [Bosun](96-bosun.md) |
| `keel/authority.py` | what actor `bosun` may do, as refusals: Bosun's key, the verb allowlist, builder mode's writes, the outcome gate checks, its authority paths | [Bosun](96-bosun.md) |
| `keel/repair.py` | Bosun's repairs of a card's board mechanics in every space (c-575): the paths Keel reads, a house whose block Keel wrote, a same-stage replay; each recorded with its `--why` (no limit, c-593), and the path facts read from this machine's disk (`repair_facts`); an authority path | [Bosun](96-bosun.md) |
| `keel/repairhouse.py` | Bosun's house repairs carried to the house (c-593, out of the retired `drive`): `kb console resume` and `retry`, each with `--why`; an authority path | [Bosun](96-bosun.md) |
| `keel/pausewake.py` | the drain's wake of Bosun for a house auto mode paused on any card (c-584), and for the user's taps on Bosun's own work, the `tell` events (c-734): `kb console wakes` and `woke`, and the message's words | [Bosun](96-bosun.md) |
| `keel/consolehandoff.py` | Bosun's compaction: the PreCompact hook `keel console handoff` that writes the handoff note and the Journal's row, and what SessionStart prints after a compaction | [Bosun](96-bosun.md) |
| `keel/consolejournal.py` | what the Journal reads beside the moves: cards done by space in the last seven days and the recurring gaps | [Bosun](96-bosun.md) |
| `keel/gitgate.py` | the git gate, left from Bosun as its own Unix user (retired, c-648): a gated ssh key fetches and pushes Keel's repo through a forced `bin/keel-git-gate`, and `bin/keel-git-receive` (the repo's pre-receive) lets it move `next` forward and its `bosun/*` branches, never `main` | [Bosun](96-bosun.md) |
| `keel/consolewake.py` | waking Bosun with the user's answers and with the houses auto mode paused: a message into its live session (never a stop), only when it is idle, and what a relay that failed does next | [Bosun](96-bosun.md) |
| `keel/reviewreap.py` | a done review card's worktree reaped (c-734): only the path its pack recorded, by `git worktree remove`, never under a session the harness lists, once a round; a pack that answers `later`, or whose reap command fails, is asked again (c-743) | [The drain](30-drain.md) |
| `keel/buildout.py` | build output a house never commits (c-734): a copy the install made carries the common caches and dependency folders in its own `info/exclude`, at the copy and at every cut | [Onboarding](89-onboarding.md) |
| `keel/bosuncards.py` | a Keel card on the user's personal board (c-592): who filed it (its create event), Bosun's state (plan, queued, building, on next, live, the last two from git via `deploy.carried`, the deploy asks as fallback) and whether the user's board shows it, as `derived.keel_card` on the deck's cards | [Bosun](96-bosun.md) |
| `keel/bosunhold.py` | Bosun's voice hold: the board's `holds` row keyed `bosun`, `kb console held` and `kb console hold`, who may write it | [Bosun](96-bosun.md) |
| `keel/bosuntalk.py` | "put me through to Bosun": `keel converse bosun`'s board half (connect, answer, release), the session's half (plan, guards, flagless wake, Journal), and what ends a hold without the user (a tap, the drain) | [Bosun](96-bosun.md) |
| `keel/rotate.py` | rotating a house on demand: the checkpoint turn, then a fresh session rehydrated from it (`house.rotate`, `keel rotate <card>`) | [houses](20-houses.md) |
| `keel/review/` | the review core and the pre-gate pipeline (review, verify, preship, risk): the reviewer and verifier `--agents` defines (`agents.py`), the finding schema and the verifier's rules (`findings.py`), the standards loader (`standards.py`), the risk score (`risk.py`), the brief's section (`brief.py`), `bin/keel-review` (`prep.py`), the stamp `bin/keel-review-stamp` writes on `SubagentStop` (`stamp.py`), the Stop hook's check (`gate.py`), the checks at `kb stage review` (`stagecheck.py`), the git questions (`repo.py`), the house's own test run the stamp records (`testrun.py`, c-544), twins the adapter names, reviewed once through the member they follow (`twins.py`), and a review card's rounds and last-round ledger for its lint (`ledger.py`, lane RC) | [houses](20-houses.md) |
| `keel/drain.py` | the drain role: claim, start, reconcile | [the drain](30-drain.md) |
| `keel/passlock.py` | one drain pass at a time per install: the pass's lock on `state/drain-pass.lock`, which an unscoped pass skips on and a card-scoped one waits for (c-734) | [the drain](30-drain.md) |
| `keel/livestrip.py` | the live strip (c-599): what each live house is doing now, read from this machine's houses by the deck's `Watcher` only while a stream is open, held in the deck's memory (`Strip`) and said on the event stream as `live <c-id> <json>`; never the board | [the deck](40-deck.md) |
| `keel/livetail.py` | a house's job record and the tail of its transcript read for the live strip: last tool, todo progress, turn start and end, newest write, the harness's own `detail` line; parsed again only when the file moved | [the deck](40-deck.md) |
| `keel/housejobs.py` | a house's background jobs: the harness's job record read, an idle house's running jobs for the deck and the drain's note, and the stop that ends the shells `claude stop` left, by pid proven by start time; and the one rule for a working house (`working`: a listed process in a turn), which landing, resume, the deck and Bosun's read all ask | [houses](20-houses.md) |
| `keel/housemem.py` | the memory a live house holds (c-607): the RSS of the listed pid's process tree, from `/proc` on Linux and `ps` on macOS, read with the live strip's facts, in memory only | [houses](20-houses.md) |
| `keel/idleclose.py` | Close idle house (c-607, `house.close_idle`): the idle rule checked at the tap, and the `closed-idle` note that the next batch or the user's tap undoes | [houses](20-houses.md) |
| `keel/shipidle.py` | the drain's three ends of an idle house (a-72, c-651): a card its merge made done has its idle house ended, a shipping house whose turn on a re-offered batch ended, or idle over two hours by its own Stop, is closed until its next batch; never a working house, checked again right before the stop; what a re-offered batch's turn left unjudged blocks the card for the user (c-654) | [the drain](30-drain.md) |
| `keel/ghosts.py` | the doctor's `ghost houses` line: every row the harness lists as working with no process behind it (r-26), a problem naming its card | [houses](20-houses.md) |
| `keel/permpause.py` | a house auto mode paused on a permission prompt: the harness's two signals, the denied commands read from the transcript, the drain's marked block and its clear | [the drain](30-drain.md) |
| `keel/trackclose.py` | a tracking card whose slices are all done closed to done by the drain (`Board.close_tracking`), with a rollup of its slices as its outcome (`outcome.md`), unless the user holds or blocks it or an ask is open; taken back to tracking when a slice leaves done, at review or after the close | [cards and gates](10-cards-and-gates.md) |
| `keel/login.py` | whether a space's login still works: the harness's own words for a lost one, one `claude -p` probe, the answer kept ten minutes in `state/login.json` | [the drain](30-drain.md) |
| `keel/logins.py` | the Logins list (c-558): one row per credential this machine depends on, the marks a failure leaves, the drain's due checks, `keel logins` | [the drain](30-drain.md) |
| `keel/loginprobe.py` | the cheap check per kind of credential (a Claude dir, Drive, OCI, a voice key, an adapter's rows) and each one's one-liner | [the drain](30-drain.md) |
| `keel/loginask.py` | the login ask: one per red episode of a Logins row, withdrawn when it answers good | [the drain](30-drain.md) |
| `voice/harbor_voice/loginmark.py` | the voice gateway's marks on the Logins list: a key Google TTS or Jev refused marks its row, the next success takes the mark off | [the drain](30-drain.md) |
| `keel/loginhold.py` | a card held for its space's expired login: the marked block, the marker read back from events, the one resume once it works | [the drain](30-drain.md) |
| `keel/boardlist.py` | the deck's board list: every board with its card's title and story, and one search across the board files | [the board](45-board.md) |
| `keel/boardgrammar.py` | the board's grammar version, the card generated from the parser that every copy embeds, and the translator for the grammar before it | [the board](45-board.md) |
| `keel/serve.py` | the serve role: the HTTP deck, the static page, the lavish proxy | [the deck](40-deck.md) |
| `keel/childenv.py` | what no child Keel starts may inherit (`KEEL_TOKEN`, `KEEL_LIVE_STATE`), and the one helper every child environment is built with | [houses](20-houses.md) |
| `keel/deckauth.py` | who may act through the deck as the user: the page's per-process cookie, the browser's same-origin word, the origin rules the routes share | [the deck](40-deck.md) |
| `keel/voicetier.py` | the deck's `/voice/` routes: the gateway proxied, the websocket spliced | [the talker and voice](50-talker-and-voice.md) |
| `keel/refinescope.py` | the capture refine's second belt in `kb`: with `KEEL_REFINE_CARD` set (empty refuses everything), writes only to that card, no links, never a gate verb, always as `voice` | [the talker and voice](50-talker-and-voice.md) |
| `keel/judges.py` | the judges' switch (`keel voice judge`) and the shadow report (`keel voice judges`), which skips call lines with no transcript turn | [the talker and voice](50-talker-and-voice.md) |
| `keel/judgeverdict.py` | `keel voice judges --since`: flip on, drop or needs more data per judge key, on personal turns, from outcomes and the user's labels, never printing a word said (c-552) | [the talker and voice](50-talker-and-voice.md) |
| `keel/voicelatency.py` | `keel voice latency`: each voice turn's stages (end, transcript, first words, first audio) read off the transcript, p50 and p95 per tier, read only | [the talker and voice](50-talker-and-voice.md) |
| `keel/housetier.py` | the house tier: the routes a house calls the deck on, answered on loopback only with this machine's own house key (Bosun's key is derived from it) | [houses](20-houses.md) |
| `keel/planroute.py` | a plan or outcome page's reads: `format_docs`, `outcome_path`, `local_plan` | [plans on the deck](47-plans.md) |
| `keel/cardfiles.py` | the markdown files a card wrote, listed and read in the viewer from inside its folder only | [plans on the deck](47-plans.md) |
| `keel/deploy.py` | the deploy: the drain's step that raises the deploy ask when the integration branch is ahead of main, and the worker the user's Yes starts (every module with voice, `[deploy_tests]` (`make test-all` for Keel), skipped only for a tree a full run proved: a landing whose run was every module, or `kb tested` after a green `make test-all`; one rerun of failures; main fast-forwarded) | [the drain](30-drain.md) |
| `keel/refresh.py` | what a move of main refreshes: the paths the voice gateway and Harbor's memory run on, their stamps read from HEAD (the talker's memory from the install's memory repo once it holds it, c-722), and the deploy record's words for them (c-538) | [the drain](30-drain.md) |
| `keel/restart.py` | the code-moved restart: the head this process loaded (pushed as `loaded`, in `state/drain.json`) and the quiet it waits for, no conversation or house call in flight (c-557); `stamp` and `moved`, which the fetch role's own restart reads (c-742) | [the drain](30-drain.md) |
| `keel/deploypreflight.py` | the deploy's preflight (c-725): a tree of Keel's own code is refused, before its suite, while the install would read a path it removes (any path-valued setting, `settings.PATH_KEYS`; an adapter; a service of the install's or a launch agent, loaded or not, with `KEEL_HOME` the checkout and no `KEEL_CONFIG` while the tree drops `keel.toml`; the talker's rulebook) or would lose one owner's things the old tree held (`movepersonal.pending`); each problem names the command that clears it, and a launchd it cannot read is a problem, never a pass | [the drain](30-drain.md) |
| `keel/deployask.py` | the deploy ask: raised by the drain once per sha, answered only by the user's tap or voice, `kb console deploy`; where a deploy stands, phase by phase (`steps_of`) | [the drain](30-drain.md) |
| `keel/landing.py` | the landing queue: Approve outcome carried to the worker that lands it, and the pre-run at review (`merge_queue`) | [cards and gates](10-cards-and-gates.md) |
| `keel/dropin.py` | Drop in: the command that enters a card's house from the desk (attach a live one, resume an exited one) | [the deck](40-deck.md) |
| `keel/deckstate.py` | the state document, and one card's detail | [the deck](40-deck.md) |
| `keel/deckreload.py` | a config change the running deck reads in place (c-729), and the ones that still re-exec it: what the process bound at start (its port, its state, voice) | [onboarding](89-onboarding.md) |
| `keel/readings.py` | the deck's slow readings (`act links`, verbs, providers, git, `claude agents`) kept between builds and refreshed on their own threads (c-638) | [the deck](40-deck.md) |
| `keel/lavishlayer.py` | the phone layer the lavish proxy injects into a lavish page | [the deck](40-deck.md) |
| `keel/deckdigest.py` | the deck read over loopback, and the one reduction both Harbors answer from: `keel deck` prints it, a voice turn carries it | [the talker and voice](50-talker-and-voice.md) |
| `keel/actions.py` | every deck verb | [the deck](40-deck.md) |
| `keel/openapp.py` | Resume and open in app: the house woken with no turn, and the claude.ai link of its current session (`house.open_app`) | [the deck](40-deck.md) |
| `keel/artifacts.py` | artifact tokens, the roots, the denylist, the markdown renderer | [the deck](40-deck.md) |
| `keel/atlas.py` | this documentation's page list and one rendered page | [the deck](40-deck.md) |
| `keel/fetch.py` | the fetch role: segment fetchers, asks to cards, and the fold that closes an ask card: what one pass does | [segments](70-segments-and-fetch.md) |
| `keel/fetchloop.py` | the fetch role's loop: the passes on their schedule, what the first one will file said before it runs, and its own restart onto moved code or config between passes (c-742) | [segments](70-segments-and-fetch.md) |
| `keel/fetchpreview.py` | what the next full fetch pass would file (asks, recurring cards), read and never written: `keel fetch --preview`, and the role's `first pass:` log lines (c-742) | [segments](70-segments-and-fetch.md) |
| `keel/recurring.py` | the cards the fetch role files again on a schedule (`[recurring.<key>]`), due from the board alone | [segments](70-segments-and-fetch.md) |
| `keel/segments.py` | the deck's segment tier: a segment's data files, and the two drops it accepts | [segments](70-segments-and-fetch.md) |
| `keel/adapters.py` | adapter discovery and invocation | [the work adapter](60-work-adapter.md) |
| `keel/packs.py` | packs: finding one, validating its `pack.toml`, its declared checks, each pack's `drift-terms` | [packs](62-packs.md) |
| `keel/packclones.py` | a pack someone shared (c-740): a pack that is its own clone inside the install's packs folder, which the packs repo ignores by a marked block in its `info/exclude`, whose head the drain's restart check reads, and which is one of the install's own repos (`pack-<name>`) for Bosun to build | [packs](62-packs.md), "A pack someone shared" |
| `keel/scaffold.py` | `keel new <kind> <name>` (a pack, a segment or a view): a checked starting point per kind, in the checkout or with `--install` the install's own directories (c-634); `keel new pack <name> --kit` starts a code host pack on the pack kit instead (c-735) | [extending](63-extending.md) |
| `keel/scaffoldkit.py` | the files `keel new pack <name> --kit` writes: shims over the kit, a host layer whose operations are stubs, its checks, its guard policy, a stand-in hook and the conformance file (c-735) | [extending](63-extending.md) |
| `keel/packcheck.py` | `keel pack check <dir>`: a pack's own suite run in a process of its own, and the conformance contracts its claims call for, in one line (c-735) | [packs](62-packs.md) |
| `keel/packkit/` | the pack kit (c-735): what every code host pack shares (the card, the cut, the drafts, Ship, sight, review cards, the brief, the verbs, the requirement rows, the guard and its reader), the host layer contract (`layer.py`), two transports (`cli.py`, `rest.py`) and the conformance suite (`world.py`, `standin.py`, `conformance.py`, `lifecontract.py`) | [packs](62-packs.md) |
| `packs/gitea/` | the Gitea pack (c-735): a code host on the kit, pull requests on a Gitea through its API with the sign-in git keeps (`gt_layer.py`, `gt_ready.py`, `gt_fence.py`) | [packs](62-packs.md) |
| `keel/deckviews.py` | `app/views.json`, the deck's one list of views and scripts: its check, the page's script tags and `window.KEEL_VIEWS`, the worker's shell and cache hash, the served scripts (c-634) | [extending](63-extending.md) |
| `keel/segmentspec.py` | what a segment's `segment.md` frontmatter may say, checked; `keel doctor` reports a segment that fails (c-634) | [extending](63-extending.md) |
| `keel/ciroute.py` | a card's CI page, `/ci/<id>` on the plan page's shell, and its data, the pack's `ci <id>` (c-642) | [a card's CI](66-ci.md) |
| `keel/commentsroute.py` | a card's review comments page, `/comments/<id>` on the plan page's shell, and its data, the rounds its house was told (c-643) | [a card's review comments](67-comments.md) |
| `keel/flows.py` | a space's flow: the format and its shape check, which flow a space has (its own, its pack's, Keel's `etc/flows/`), the space's words filled in, how it is drawn, `keel flow check|show` (c-640, c-664) | [flows](64-flows.md) |
| `keel/flowcheck.py` | whether a flow can run: the moves that never could, and with the space, the steps and the `opens` it cannot carry out; behind `keel flow check` and Adopt (c-664) | [flows](64-flows.md) |
| `keel/bases.py` | a space's bases, the branches a card's work starts from and lands on: the one list the card form, both drafts and How work ships read, and How work ships' questions (c-732) | [flows](64-flows.md) |
| `keel/flowcards.py` | a flow proposed by a house from your words (the brief's format written from the schema's key lists), adopted by your tap, or reset to the pack's or Keel's (c-640) | [flows](64-flows.md) |
| `keel/flowmoves.py` | a move of the flow you make on a card: checked (held while the branch is out of step), granted to the card, told to its house (c-640) | [flows](64-flows.md) |
| `keel/flowfence.py` | the push fence a flow draws: a push's destinations, the shared branches, the grant (ended when the flow renames its branch), and `kb flowpush` (c-641) | [flows](64-flows.md) |
| `keel/terms.py` | what a space calls a ticket and a change: the core's neutral defaults with the pack's `[terms]` laid over them, the templates notes and briefs fill, the plan page's ticket and change refs (c-630) | [packs](62-packs.md) |
| `<install>/packs/<name>/` | an install's own pack, outside the code: a work pack (an adapter, its stack's rules, the tools it declares) lives there, copied in by `shipyard move-personal` | [the work adapter](60-work-adapter.md) |
| `packs/sandbox/` | the sandbox adapter, the example pack: the work verbs over a JSON code host and tracker under the sandbox, for the demo | [the work adapter](60-work-adapter.md) |
| `adapters/` | a link to `packs/sandbox` that keeps the old adapter path working | [packs](62-packs.md) |
| `demo/sandbox/setup`, `demo/sandbox/run` | the demo sandbox built from nothing (and `--clean`), and the one door every command takes into it | [the work adapter](60-work-adapter.md) |
| `demo/seed`, `demo/seeding/` | the demo's seeded day on the sandbox board, a phase per point in the script | [the work adapter](60-work-adapter.md) |
| `demo/scenes/` | the demo's scenes as `keel-browser video` steps, the recorder with its employer sweep and index, the contact sheet, and the sandbox's Harbor (gateway, mic, capture) | [the work adapter](60-work-adapter.md) |
| `demo/build` | the demo video from nothing: setup, the day recorded in order, the edit, the evidence | [the demo video](65-demo.md) |
| `demo/video/` | the Remotion edit: the cut keyed to the takes' names and steps, prepare, render scene by scene, evidence; not in the public release (`.gitattributes`) | [the demo video](65-demo.md) |
| `demo/music/` | the CC0 music bed and its credits; not in the public release (`.gitattributes`) | [the demo video](65-demo.md) |
| `.gitattributes` | what the public release (`git archive`) leaves out: `demo/video/` and `demo/music/` | [the demo video](65-demo.md) |
| `keel/talker.py` | the talker's runtime verbs, and its health read off the state files | [the talker](50-talker-and-voice.md) |
| `keel/talkerdirs.py` | the talker's config dir and run dirs: the `.claude.json` seed, the memory link, rotate, prune, forget (re-exported by `keel/talker.py`) | [the talker](50-talker-and-voice.md) |
| `keel/talkerturn.py` | the phone talker's turn hooks (`keel talker turn`), the memory stamp each run starts on, and when a memory change may rotate it (c-538) | [the talker](50-talker-and-voice.md) |
| `keel/talkerwatch.py` | the talker's output read in chunks, its start stamp and fault file, and the pure health verdict | [the talker](50-talker-and-voice.md) |
| `keel/claudejson.py` | a config dir's `.claude.json`: read, written whole in one rename, the talker's consent asserted, a file that does not parse never written over | [the talker](50-talker-and-voice.md) |
| `keel/trust.py` | a house's cwd trusted in its space's `.claude.json` before every `claude --bg` start, resume and wake, and forgotten when the worktree is reaped or the errand's house retired | [houses](20-houses.md) |
| `keel/atomicfile.py` | one file replaced in one rename (temp beside it, fsync, `os.replace`) | [the talker](50-talker-and-voice.md) |
| `keel/voice.py` | the voice gateway from Keel's side: `keel voice venv`, `install`, `uninstall`, `status`, `key set|check` (the Google key on Linux), `audio` (the rendered filler clips), `latency` (per-stage timing, `keel/voicelatency.py`), and the health probe | [the talker and voice](50-talker-and-voice.md) |
| `keel/install.py` | `keel install`: the engine's launchd agent or systemd unit | [cutover](80-cutover.md) |
| `keel/installer.py` | `shipyard init <dir>`: an install for one user on one machine, its config, board, own Claude dir, trust, wrappers, memory, services and doctor; safe to re-run | [install](88-install.md) |
| `keel/movepersonal.py` | `shipyard move-personal`: an owner's own things (the work pack, five segments, the memory, the profile, the history docs, the settings the install lacks) copied from the checkout into the install once, never over what is there, never deleting, `--dry-run` | [install](88-install.md) |
| `keel/memoryroot.py` | the install's memory (c-722): Bosun's and the talker's under `<install>/memory` (a git repo) and the profile in `<install>/identity`, seeded once from `templates/`, read before the checkout's, the doctor's `memory` lines | [Bosun](96-bosun.md) |
| `keel/stateimport.py` | `shipyard import <dir>`: a keel snapshot brought into an install by an allowlist, its refusals, the segments, the record, `--replace`, `--dry-run` | [import](87-import.md) |
| `keel/importboard.py` | the import's board edits: planned from the snapshot (paths, two machines' fields, box sessions, worktrees cut again), made in one transaction on a copy | [import](87-import.md) |
| `keel/importpaths.py` | the import's old state roots (`<checkout>/state/`) found from stored values, and a value under one moved | [import](87-import.md) |
| `keel/drainprobe.py` | the Keel drains running as this user on this machine (processes and their `KEEL_CONFIG`, old launchd and systemd labels), which refuse an import and a service start and the doctor names; and the processes running the fetch role for this install (`fetching`, c-742) | [import](87-import.md) |
| `keel/importconfig.py` | the old config's choices carried into an install's `config.toml`, the two-machine tables never | [import](87-import.md) |
| `keel/importverify.py` | the import's checks (counts, card dirs, leftover roots, integrity, new plan findings, the doctor) and `state/import/report.md` | [import](87-import.md) |
| `keel/onboarding.py` | the deck's Setup view: its report (tiers, repos, proposals, packs) and the setup verbs: clone, attach, remove, add a space, pack on, tier save, propose, adopt; `adopt_proposal`, the one way a tier or flow proposal's draft is written, by Adopt or by Approve outcome on its card (c-667) | [onboarding](89-onboarding.md) |
| `keel/reposetup.py` | Add your repos, the part that touches git and the config (c-618, c-632, c-678; out of `keel/onboarding.py` in the c-678 review): the clone into the layout with its refusal sorted into a kind, the add that makes the space, the attach of a checkout where it is, a plain space with fetch before work and offer Push written on, and the remove refused while an open card names the repo | [onboarding](89-onboarding.md) |
| `keel/packdraft.py` | Another provider (c-678): the card on which the in-app builder drafts a connection for a code host Keel ships none for (`setup.pack.draft`), and how that card stands for the Setup report | [onboarding](89-onboarding.md) |
| `keel/firstrunsteps.py` | how each first-run step reads as done (c-632, c-678; out of `keel/firstrun.py` in the c-678 review): one function a core step (`STATE`), the two builder forms, and a pack step's state; done is read each time and never stored | [onboarding](89-onboarding.md) |
| `keel/firstrun.py` | the first-run stepper (c-632): the steps in order with pack steps, done read from readiness, `state/firstrun.json` (skips and Finish only), the redirect, and the `firstrun.*` verbs | [onboarding](89-onboarding.md) |
| `keel/setupconfig.py` | what the setup verbs share: the install a config belongs to, and the checked, backed-up write of its config | [onboarding](89-onboarding.md) |
| `keel/settings.py` | the settings schema: every user-facing key of `[keel]`, `[spaces.<name>]` and `[voice]`, and `[builder] mode`, with its type, default, label and help; the loader's typed reads and warnings, and the Settings view's report and Save | [the configuration](00-start-here.md), [the deck](40-deck.md) |
| `keel/packsetup.py` | packs on the Setup view: each with its checks and rules, Turn on (a space on the pack's example, `pack_space`, which `shipyard import` makes too, or a plain space adopted, `adopt_space`), Turn off (`pack_off`: the pack and what Turn on wrote for it, refused while the space has open cards), and which packs are offered (`offered`: a demo-only one never on an install) | [onboarding](89-onboarding.md) |
| `keel/tiercards.py` | a repo tier proposed by an errand house from the clone, and adopted by the user into the repo tier (Adopt, or Approve outcome on its card) | [onboarding](89-onboarding.md) |
| `keel/repolayout.py` | an install's layout: `spaces/<space>/<key>/` with its tier, its clone and its cards' `trees/`, and the `claudeMdExcludes` that keep the team's CLAUDE.md out of a house | [onboarding](89-onboarding.md) |
| `keel/configedit.py` | an install's `config.toml` edited one table at a time, comments kept, a backup kept, refused when the file moved, put back when Keel would not load it | [onboarding](89-onboarding.md) |
| `keel/prereqs.py` | the machine checks `shipyard init` makes first: OS, Python, sqlite3, git and its name and email, `claude` and its harness features, node when a feature needs it; each carries the three parts of its miss (what happened, the fix and its command, whether it is required), and `save_identity` writes git's name and email for the deck | [install](88-install.md) |
| `keel/appservices.py` | `shipyard service install|start|stop|status|uninstall`: an install's deck, drain and fetch role as launchd agents or systemd user units; `install` leaves a current, loaded one running, and `bring_up` (the drain, as it starts) adds one that is missing (c-742); "started" is said only of a service the manager reports a process for, and a bring-up with none is started at the next drain start (c-747) | [install](88-install.md) |
| `keel/service.py` | one service as a launchd plist or a systemd user unit (and timer), loaded, started, stopped, read, restarted and removed on either, and refused on any other OS; on launchd a load ends with a kickstart, since a bootstrap is not a start, and `running` waits a bounded time for a pid (c-747, [install](88-install.md)) | [cutover](80-cutover.md) |
| `keel/backup.py` | `keel backup`: the backup jobs (snapshot, verify, the nightly pull), `keel backup env`, and the verbs that drive `bin/keel-backup` | [the backup](85-backup.md) |
| `keel/backupdue.py` | the hourly snapshot watched from the drain (c-750): started when the service manager did not start it, one `backup-stale` notice after two waking hours with a run owed and no success, and the doctor's `backup` line | [the backup](85-backup.md), "When the hourly job stops" |
| `keel/backupslim.py` | the sums behind `keel backup slim` (c-724), called by `bin/keel-backup`: what the set's own scan leaves out of an unpacked old snapshot, by rule, and the proof that the rewritten archive is the old one minus exactly that; its command line carries the two modules below | [the backup](85-backup.md) |
| `keel/backupslimapproval.py` | the slim's approval file, `slim-approved.json` in the backup home: what the dry run showed per snapshot (the object's md5, a digest of everything that decides a drop, a digest of the dropped paths and of the roots, the totals by rule, each tree dropped on the live tree's word), and the checks that make `slim --approved` do exactly that and nothing else | [the backup](85-backup.md) |
| `keel/backupslimjournal.py` | a set's `slim.json`, the journal of that rewrite in the store: which snapshots are slim (by the md5 the store holds and the digest of the rules each was slimmed under), the one mid-replace, the snapshots still to do, which kept old archives a purge takes, and a `latest.json` made to describe a rewritten snapshot | [the backup](85-backup.md) |
| `keel/backupslimreport.py` | what a slim run says: one line a snapshot, then the totals by rule and the rough time | [the backup](85-backup.md) |
| `keel/dockerroom.py` | the doctor's `docker` line: on a Mac that runs houses, Docker Desktop's memory against the machine's, and 6 GB or less left for macOS is a problem | [cutover](80-cutover.md) |
| `keel/doctorpacks.py` | `keel doctor`'s pack lines: the pack behind a space, its tools with their checks run here (`pack_report`), and the line printed for it with each missing tool's own fix under it (`pack_lines`, `fix_lines`, c-688) | [packs](62-packs.md) |
| `keel/doctor.py` | `keel doctor`: the resolved setup (live board counts, the talker's health, the voice gateway's health, the deck's descriptor count, fetch staleness read from `keel/fetch.py`, on an install whether its fetch role runs, and each space's login probed for real, then a `login` line per other row of the Logins list, a red one a problem, and a `backup` line with the last good run, a problem when the drain has counted the hourly snapshot overdue, `keel/backupdue.py`), exit 1 on anything missing ([install](88-install.md)) | [cutover](80-cutover.md) |
| `keel/health.py` | one verdict for "is Keel healthy" (green, amber, red, and the reasons) from the doctor's facts, on the deck's state document as `health` | [the deck](40-deck.md) |

### The configuration

**Where it lives (c-610 S1).** An install reads `<home>/config.toml`, where the home is
`KEEL_HOME` (every service sets it), else the checkout the code is in. That file is
gitignored: it holds one user's choices and one machine's paths, and neither belongs in the
tracked tree. No one's own config is tracked (c-722 landing B: the `keel.toml` the tree
carried was one owner's, and went to that owner's install). Without a `config.toml`, an
untracked `keel.toml` an older checkout kept is read, else the shipped defaults,
`etc/shipyard.example.toml`: the example of every key with no hostname and no personal path
in it, whose state is anchored to a home and so is a scratch board for a clone or a
worktree. It is read only by a house worktree or a test (c-725 r1.F5): in a
checkout whose `.git` is a directory, with no `KEEL_CARD` and no test fence, that load
refuses, naming `KEEL_CONFIG` (`config.example_refused`). `KEEL_CONFIG` still names a file outright and wins over all three
(`config.config_path`, `config.config_file`). `shipyard init` makes an install's
`config.toml` from the example, which the install's
wrappers and services name with `KEEL_CONFIG` ([install](88-install.md)). Which file it is
has one answer, `keel/configpath.py`. A service file carries `KEEL_CONFIG` when its config
is not the checkout's own (c-711): the engine's and the voice gateway's through
`config.named_env`, the talker's through the same rule (`config.named_toml`, kept on its
`Paths`). An install's deck, drain and fetch role name `<install>/config.toml` themselves
(`keel/appservices.py`), since they exist only for an install, and the backup jobs name the
config they were installed with. The voice gateway, which reads only `[voice.judges]`, asks
the same function for its file (`voice/harbor_voice/config.py`, `KEEL_TOML`).

**One file, two concerns, split by table.** What a user CHOOSES is `[keel]` (the switches
below), `[spaces.<name>]`, `[voice]`, `[tests]`, `[house_tests]`, `[integration]`,
`[retests]`, `[deploy_tests]`, `[recurring.<key>]` and `[models]`. What the MACHINE needs is `[machine]`
(`config.MACHINE_KEYS`, table below), `[backup]` and `[console]`. One file rather than two,
because a user edits one thing and a single table boundary keeps the two apart as well as a
second file would, without a second lookup that has to agree with the first. A `[machine]`
key wins over the same key under `[keel]` (and `voice_port`, `voice_app_url`,
`voice_deck_url` over `[voice]`'s `port`, `app_url`, `deck_url`), so a file written before
the split loads to the identical Config; an unknown `[machine]` key is refused.

**One schema for what a user chooses (c-633).** Every user-facing key of `[keel]`,
`[spaces.<name>]` and `[voice]` is declared once in `keel/settings.py`: its table, whether it
is the install's or a space's, its type and range, its default, a label and a sentence of
help. `config.load` reads those three tables through `settings.check`, so every default is
the schema's (the `Config` and `Space` dataclasses read theirs from it too, so a `Space` built
in a test agrees with a loaded one) and every value is typed: a `bool` is only `true` or
`false`, never the string `"false"`. Two things that used to be silent are now said:

- **A key a table does not know** (`house_reveiw = true` under a space) is a line in
  `Config.warnings` naming the closest real key ("did you mean `house_review`?"). The keys a
  table accepts that are not settings (paths, `repos`, `pack`, this machine's own keys, the
  host limits `[keel]` may hold, `[voice.judges]`) are `settings.STRUCTURAL`, and never warn.
  A pack's `[space]` defaults are checked too, and the line names the pack.
- **A value of the wrong type or out of range** (`houses_max = "3"`, an unknown model) is a
  warning naming the key, the value and what it may be, and the schema's default is used,
  or the setting's safe `fallback` where that is not its default: a garbled `drain_paused`
  pauses the drain (c-628 review).
  The loader never refuses a config for it, so a typo can never keep the deck from starting
  (Bosun's condition at the plan gate). The Settings view's Save refuses the same value.

Now draws the warnings in a panel with a way to Settings (`config.warnings` in the state
document), and `keel doctor` lists each as a problem. `[machine]`,
`[recurring.<key>]` and `[models]` keep their own checks and still refuse a stranger.

Two defaults changed to match the shipped example: `drain_paused` is false and
`house_review` is true when the file leaves them out. Six switches stay off in code although
the example turns them on (`merge_queue`, `rotate`, `multi_after`, `bosun_builder`, and
`[voice]` `harbor_kept_alive` and `record`): each is a feature whose off position is the safe
one, and `settings.EXAMPLE_OPT_INS` writes them down so `tests/test_settings.py` holds the
example and the schema together on every other key.

| Setting | Table | What it decides, and its default |
|---|---|---|
| `model` | `[keel]` | Keel's own model for a new card when neither the card nor its space names one (the `keel_default` layer, and `house.require_model`'s suggestion); opus |
| `reviews_max` | `[keel]` | review cards at once, in their own pool; 2 |
| `review_full_rounds` | `[keel]` | full review passes per trip for a space that names none (`review/stamp.py`); 2 |
| `review_asks` | `[keel]` | the asks for a missing review stamp before the card is blocked (`review/gate.py`); 2 |
| `merge_test_seconds`, `deploy_test_seconds` | `[keel]` | how long the merged-tree tests (`merging.run_tests`) and the deploy suite (`deploy.run_suite`) may run; 900 and 1800 |
| `ship_idle_hours` | `[keel]` | a shipping house idle this long is closed (`shipidle.close_idle`), and the deck says the same hours (`views.ship_idle`, through `Board.ship_idle_hours`); 2 |
| `ship_auto_comments`, `ship_auto_checks` | `[spaces.<name>]` | whether a shipping card's new review comments, and its failing checks, go to its house as they arrive (`shipauto.for_card`); a card's own option of the same name wins. Off, they are kept on the card as `untold` until the user hands them over; off and off (c-655: every card was automatic before) |
| `voice_hold_seconds`, `talker_reset_max_age_seconds` | `[keel]` | how long voice holds a house after the user's last sentence, and when the talker starts a fresh conversation; 300 and 86400 |
| `autonomy`, `plan_style`, `topic` | `[spaces.<name>]` | a new card's autonomy, plan style and topic when it names none (the `space_default` layer and the card form's defaults; the brief says the plan style); autonomous, auto, none |
| `reviewer_model` | `[spaces.<name>]` | the model the house's reviewer and verifier run on (`review/agents.py`); `inherit`, the house's own. Not `review_model` |
| `remote` | `[spaces.<name>]` | the git remote the space's repos fetch from and push to (c-665). Read through ONE helper, `config.remote_of`, by everything that names a remote for a card's repo: the shipping read of a worktree against its branch and its base (`shipping.tracked`, `shipping.conflicts`), the by-hand command (`shipstep.chain`), `kb flowpush` and the guard's refusal (`flowfence`, which carries it in `kb flowinfo` so the house's machine pushes where the board's host says), and the words a house is told (the rebase item, the preship step, the stage check's refusal). The review's base is read on it too: `review/repo.py`'s `fetch_base` and `base_ref` take the remote from whoever has the card or the space (the stage check and the outcome's claim check through `plangate`, `keel check` through `fixcheck`, the Stop hook's and the shipping read's `gate.covers`), and the house's own `keel-review prep` is told `--remote <name>` in its brief when the space's is not `origin`; a guard's read of a bare `git push` (`flowfence.targets`) and `keel doctor`'s neighbour scan read it as well. A reader with no config at hand is handed the name. Three cannot be handed it and read `origin`: Bosun's outcome facts (`authority.outcome_facts`, which calls `gate.covers` with no remote), the stamp's fallback for a prep file from before heads were recorded (`stamp.prepared_heads`, a hook with only its payload), and a review card's prep line (`brief.peer_block`). There the base falls back to the local branch, as for a repo with no remote. A pack runs its own git; `origin` |
| `branch` | `[spaces.<name>]` | how a new card's branch is named in a space with NO pack (c-665; a pack names its own): a pattern that fills `{id}` (the card's id) and `{slug}` (its title in a few words). `adapters.git_worktree` cuts the branch by it and `adapters.existing_branch` finds it again by the same pattern, the slug any. The schema refuses a pattern with no `{id}`, one where `{id}` does not stand alone (at the start of the name or right after `-`, `_`, `/` or `.`, and followed by one of them or the end: otherwise one card's glob could take another's branch, or an unrelated one), and one git would not take as a branch name for any slug a title can give (`settings.branch_rule`, which reads git's own rules, tries a few slugs and runs no git at load). One change of pattern is covered, from the default to a custom one: when a pattern that is not the default finds no branch, the default pattern is looked under before anything is cut (`adapters.card_branch`), so a card cut under the default keeps its branch; and last under the default before c-729, `keel/<id>-<slug>` (`adapters.LEGACY_BRANCH`), so a card cut under it keeps its branch whatever the pattern now is. Two are NOT covered: from one custom pattern to another, and from a custom pattern back to the default. A card cut under the earlier custom pattern is then not found, and a new branch is cut for it. So change the pattern when no card of the space is in flight. A found name must be the whole pattern, a slug being one path part. A space with a pack ignores it, since the pack cuts the worktree. `shipyard import` reads the old default, the only one an older Keel wrote. The default is `shipyard/<id>-<slug>` (c-729: the stranger run's repo history read `keel/`), written with `{id}` and `{slug}` in braces |
| `fetch_before_work`, `offer_push` | `[spaces.<name>]` | for a space with no pack (c-678, `keel/landpush.py`): fetch the remote and fast-forward Keel's copy before a card's worktree is cut, and put a Push button on a card whose work was merged on this computer; off and off, and written on for a space the first run makes (`onboarding.add_space`), so an install from before them is unchanged |
| `review_scan` | `[spaces.<name>]` | c-730: whether the space files review cards at all, where its pack declares `reviews`; on, and a pack's `[space]` may start it off (the GitHub pack does), so a space on it is reviewed only once the user says so on Where finished work goes. Off, review scanning is not declared for the space (`readiness.undeclared`), so the drain, the Reviews route and the Reviews item all leave it out |
| `review_auto`, `review_model`, `review_sibling_hours` | `[spaces.<name>]` | the review fetcher's two settings (the Reviews gear's live override wins, and Settings shows it as the gear's), and how long a review card waits for its sibling repo; off, sonnet, 48 |
| `engine_default`, `vad`, `vad_hangover`, `kept_alive`, `harbor_kept_alive`, `record` | `[voice]` | which synthesiser speaks, the end-of-sentence detector and its silence, one process per conversation, Harbor's turns the same way, and the corpus; google, auto, 2.0, on, off, off ([the talker and voice](50-talker-and-voice.md)). The example leaves `engine_default` out, so the first run asks (c-632) |
| `mode` | `[builder]` | the builder's permission mode, auto or bypass (the superbuilder, which approves its own cards onto the integration branch) (c-632: in the schema so the first run's Choose your builder step and Settings write it; the rest of `[builder]` is `keel/builder.py`'s and is not read through `check`); auto ([Bosun](96-bosun.md)) |

The constants that stayed constants: `FIX_MAX` (`keel/fixcheck.py`), `MAX_DENIALS`
(`keel/permpause.py`), `STUCK_TRIES` (`keel/drain.py`) and the house permission mode
(`keel/harness.py`). The Settings view and its Save are on [the deck](40-deck.md) and in
[onboarding](89-onboarding.md).

| `[machine]` key | What it decides |
|---|---|
| `state_dir`, `segments_dir`, `fetch_lock_dir`, `adapters_dir` | as under `[keel]` below; the example's `state_dir` is `~/.shipyard/state`, anchored to a home so a checkout reading a copy of it from elsewhere gets a scratch board (below) |
| `serve_port`, `lavish_port`, `host`, `lavish_state`, `artifact_roots` | as under `[keel]` below |
| `voice_port`, `voice_app_url`, `voice_deck_url` | the gateway's port, Voice's own address and the deck's ([the talker and voice](50-talker-and-voice.md)) |
| `stack_guard_hook` | a `PreToolUse` guard script every house and Bosun are handed (`house.guard_hooks`); unset, none is |
| `usage_file` | the status line's usage tee the deck's meter reads (`deckstate.usage_file`; `KEEL_USAGE_FILE` wins); unset, the meter says unavailable |
| `harbor_dir` | the old Harbor tree: its `.claude/.claude.json` seeds the talker's config dir, and its `ledger/cards.jsonl` is what `kb import-harbor` reads without `--ledger`; unset, neither is read |

None of the three new path keys has a default in code: each used to be a path into one user's
own home (`~/.claude/hooks/...`, `~/.claude/helm-usage-limits.json`, `~/harbor`), and an
unset key means the feature is off on that machine. An install that wants one sets it in
its own `[machine]` table; the example leaves them unset. `[backup] legacy_repo` is the fourth new key:
the code-host repo the backup pushed to before the store, named only by `keel-backup
migrate` ([the backup](85-backup.md)).

**One machine, and old files still load (c-622).** Keel runs on one machine, so there is no
`[hosts.<name>]` table, no `[tenancy]` table, no `board_url` (under `[keel]` or `[machine]`),
no `host` key on a space, and `KEEL_HOST` and `KEEL_URL` are not read (either one set in the
environment is a warning). A file written for two machines still loads: each of those keys
is dropped and named once in `Config.warnings` as ignored, so an old config never keeps the
deck from starting (`keel/oldconfig.py`). What one machine still means is carried and named:
while `[backup]` does not say, the `backup_sets` and `backup_pull` of the old
`[hosts.<this host>]` table are read, and its limits (`houses_max`, `reviews_max` and the
`[keel]` limits below) fill what `[keel]` leaves out. `[console]` is Bosun's: a `host` naming another machine is read as this one (so Bosun runs
here), and `board_url`, `config_dir` and `checkout`, which made Bosun its own Unix user, are
dropped and named as retired ([Bosun](96-bosun.md), "Bosun's own user").

**Personal content in the tracked tree** is checked by `make drift` (and so by `make test`):
`tests/personal.py` refuses, outside `docs/`, a home path under `/Users/<name>` or
`/home/<name>` that is not a placeholder, and a tailnet host (`<host>.ts.net`) that is not an
`example` one. It needs no install, and it lets no file through: the list of files it once
let through left with the owner's things (c-722 landing B). Service files are
rendered per machine by `keel/service.py`, which is their template, into an install's
`services/` or a bare checkout's `etc/`, and every rendered one is gitignored.

**The public check is the same question, strict** (`tests/publiccheck.py`, c-699, strict since c-722 landing B).
It takes ONE install's own names (the user's name and email from git, the home path, this
machine's host names (a bare one that is a common word of a fixed list, such as `keel` (`publiccheck.COMMON_HOSTS`, never read off the tree under check, r3.F5), found only where it stands as a host: in a URL, after an @, or as a local or tailnet name; `publiccheck.as_hosts`, c-725) and the tailnet hosts the install's `config.toml` names, and the
`drift-terms` of every pack in the install and in the tree) and looks for them in every
tracked file, `docs/` included, with no file allowlist. Two short tables, each entry with
its reason, are all it lets through. `LINES` names one line of one file by its form, chosen
before any name is looked for, and the kinds that may stand on it: the first line of
`NOTICE` of the form `Copyright <year> <name>`, where the owner names themself as the
copyright holder (a name; `ALLOWED` in `tests/personal.py`, which the two checks share), and
the vendored highlight library's own copyright line (an email, kept as its license
requires). Any other kind on such a line is still a finding, and so is the same name on any
other line, a second such line, or any other file. `WAITING` names a folder of one owner's
that leaves the tree by that owner's own hand (Bosun's old memory folder, which the
authority guard refuses any builder's write to): its findings are counted in a line of
their own and fail nothing, and an entry whose folder is gone fails the suite, so it goes in
the commit that removes the folder. A file's path is read as its text is:
a name in a file name is a finding on line 0. It also flags any other person's home
path, tailnet host or email address, a symlink whose target is absolute or leaves the tree,
and, given `--range A..B`, each image the range adds and every line of its commit messages.
The install is `--install <dir>`, else the one `KEEL_CONFIG` names, else none.

It is STRICT: `make drift` runs it last with `--strict`, and any finding fails the drift
check, so it fails `make test` wherever something lands. It prints its counts by kind and by
top directory, and the path and what kind (`--list`: `path:line: kind`), never the line's text and
never the term, since a finding can sit beside a secret; a path that itself holds a name
is printed with it masked by its kind (`<install>/identity/about-<name>.md`). What it cannot read
does not fail the report either: a pack term written for `grep -E` that Python cannot
compile, or compiles only with a warning (a POSIX class), is skipped and counted in one
line that never shows it, and a git that will not list the tree or the range ends the
read with one line, and under `--strict` each of those exits 1 too. Without `--strict` it is
a report that always exits 0. The same command is what a pre-push hook and a public repo's
own checks will run, and it runs as a script too (`python3 tests/publiccheck.py`, from any
folder and with no `PYTHONPATH`: it puts its own tree first, c-729). It lives behind the test fence, so it reads the caller's names from the
environment as it was before the fence (`fence.caller()`); `tests/test_publiccheck.py`
holds it on scratch trees with made-up names. Not settled here: which install a house's
worktree, or a checkout with no install at all, should read.

The config itself (the shipped example shows every key): a `[keel]` table, a `[tests]` table (repo name to the
command Approve outcome runs on a personal card's merged tree before landing it, and the deploy
before main moves, `keel = "make test BASE={base}"`), a `[house_tests]` table (repo name to what a HOUSE runs before
review, `keel = "make test-changed BASE={base}"`, `{base}` the card's base; a repo without
one runs its `[tests]`; c-544), a `[voice]` table (`port`, the gateway's port that the deck's
`/voice/` tier proxies to, plus `space_default` and `mode_default`, the voice page's
defaults; [the talker and voice](50-talker-and-voice.md)), a `[console]` table (Bosun's
`host`, `permission_mode`, `context_window` and `compact_at`, and `repeat_after` and
`repeat_minutes`, when a failure seen again becomes a request; [Bosun](96-bosun.md)), a
`[builder]` table (`superuser`, `repos`, `mode`: which builder Bosun is, c-619;
[Bosun](96-bosun.md), "The builder"), a `[models]` table (the model
each of Keel's own turns runs on: `converse`, the voice conversation, and `refine`, the turn
per capture), then one `[spaces.<name>]` table per space with its `config_dir`, `repos`,
`contract`, `adapter` and `deny` list, its `allow` list (permission rules a house with an open shell
there runs under unasked: a repo card's, except a fork's review card; a deny still beats
one, a pack's `[space]` cannot name one and the builder's own session does not take it;
[houses](20-houses.md)), its pre-gate pipeline (`house_review`, the `pipeline`
words, `preship_first` and `review_full_rounds`, c-597; [houses](20-houses.md)), the work space's `review_backlog_days` (a quiet review
card's backlog, [cards and gates](10-cards-and-gates.md)), its `model` (what a card there runs on when nobody
names one) and its `confirm` list (the fields a card there is never filed with silently;
[cards and gates](10-cards-and-gates.md), "Where a card's fields come from").

| `[keel]` key | What it decides |
|---|---|
| `state_dir` | where the board, the card directories, the logs and the token live (a machine key: `[machine]` in a new file) |
| `adapters_dir` | where an adapter named by `adapter = "<name>"` is looked for (a space that says `pack = "<name>"` is found under `packs/` instead, [packs](62-packs.md)) |
| `segments_dir`, `fetch_lock_dir` | the segments tree, and where a fetcher's lock lives |
| `houses_max`, `poll_seconds`, `drain_paused` | the drain's pool, its cadence, and its safety catch (off when the file does not say, c-633) |
| `browsers_max`, `memory_floor_mb`, `house_mb`, `house_nice`, `idle_resume_minutes` | this machine's limits (c-622): the browser slot, the memory gate, what a house is counted at, the nice houses run at, and how long a house may sit idle mid-turn before its one resume; they sit under `[keel]` and are the drain's own ([the drain](30-drain.md)) |
| `backlog_days` | days at the outcome gate, or since the user's last own action on the card there, before it backlogs |
| `discussion_idle_seconds` | how long a plan discussion waits on a quiet surface |
| `merge_queue` | Approve outcome of a personal card lands through the drain (landing, testing, landed) and is pre-run at review; off by default (dormant), ON in the shipped example and the owner's config since 2026-09-24 ([cards and gates](10-cards-and-gates.md)) |
| `rotate` | the deck's Rotate session and `rotate` relays; off by default, ON in the shipped example and the owner's config since 2026-09-24 ([houses](20-houses.md)) |
| `multi_after` | a card may wait for several cards (`after=a,b`); off by default, ON in the shipped example and the owner's config since 2026-09-24, once every running copy read a list ([cards and gates](10-cards-and-gates.md)) |
| `bosun_builder` | builder mode: Bosun builds the personal cards on the repos `[builder] repos` names; on an install the one builder, in auto mode or bypass (shipped); the superuser only in a checkout's own config (Keel's own fixes, its own authority, the integration branch and the user's deploy kept), is the `[builder]` table (`superuser`, `repos`, `mode`); ON in the owner's config since 2026-09-29 ([Bosun](96-bosun.md), "Builder mode", "The builder") |
| `work_hours`, `work_days` | when the user works (`"09:00-19:00"`, `"mon-fri"`, local time): the pull request watcher looks every 5 or 15 minutes inside them and hourly outside ([the drain](30-drain.md), "Shipping") |
| `plan_pages` | every new plan and outcome is written in the plan format and read at `/plan/<id>` and `/outcome/<id>`; on by default and in the shipped example, and false is the way back to the plan styles ([plans on the deck](47-plans.md)) |
| `serve_port`, `host` | the deck's port, and this machine's name, which its drain pill shows |
| `lavish_port`, `lavish_state` | what the deck proxies to, and lavish's own session file |
| `artifact_roots` | the trees the deck may serve a file from, beyond the two implicit ones |
| `[backup]` | `sets` and `pull` (which of the four sets, and whether the nightly pull runs), `store`, `rclone_config` and `legacy_repo`, and `since`, when the first run turned the backup on, written by that turn-on (c-757) ([the backup](85-backup.md)) |

A path in it may be relative, in which case it resolves against the repo root, and `~`
expands. `KEEL_HOME` overrides the root and `KEEL_CONFIG` overrides which toml is read,
which is how a test and a scratch server run against a copy of the board. A `KEEL_HOME`
pointing at a directory with no `config.toml`, no `keel.toml` and no shipped example in it
is an error saying exactly that, never a fall-through to some other file. The tests that prove an old config loads
read `tests/fixtures/two-machine.toml`, the shape the tracked file had before the split.

### The state a checkout may open is its own

`state_dir` is `~/.shipyard/state` in the shipped example (an install names its own in
`config.toml`; the tracked file before c-722 said `~/keel/state`), anchored to a home and
not a path relative to the file it is written in. That file is tracked, every house builds
in a `git worktree` under `state/worktrees/<id>/`, and the worktree carries a copy of it, so
anything run from a worktree that loaded the worktree's own config would resolve
`state_dir` to a live board and write to it. `<install>/history/docs/decisions.md` (rows S1 to S8) has the
whole account.

So `keel/config.py` compares the two. A `state_dir` that resolves OUTSIDE the code root
belongs to another checkout, and this one is handed its own `state/` and `segments/`
instead: a scratch board that did not exist before. For the same
reason (E4, c-415) a scratch config serves on a port of its own and refuses the live deck's
and never reads or mints the shared house key ([houses](20-houses.md));
`KEEL_LIVE_STATE=1` is the override there too. A config that cannot load opens no board
at all: `kb` and every role refuse in one line (`cli.load_config`). On a scratch board `kb`
and every `keel` role say so in one line on stderr, and that line names the live checkout's `kb`,
which is the supported way to the live board.

**The code root is the PACKAGE'S, not `KEEL_HOME`'S**, which is the second half of the rule.
A code root read off `KEEL_HOME` is wrong:
a house's environment carries `KEEL_HOME=<the live checkout>`, so code running from a
worktree would compare the live `state_dir` against the live root, find it inside, and open
the live board anyway. That is how `bin/keel-voice-selftest`, whose capture checks speak two
phrases and expect cards back, could file real ones. `config.package_root()` is the
parent of the `keel` package's own directory, which no environment variable can move
(`bin/kb` puts its own parent's parent first on `sys.path`, so a `kb` started from a
worktree imports that worktree's package), and `borrows_state` asks both questions now:

- the `state_dir` resolves outside the root, as before; or
- the `state_dir` is the root's own, and the running package is not that root's. Compared by
  equality rather than by containment, because a worktree sits at
  `<live>/state/worktrees/<id>/`: inside the live checkout on disk, and emphatically not the
  live checkout.

A `KEEL_HOME` naming a directory with no `keel` package in it is a scratch directory nobody
else owns, so it is opened as written, which is what every test config and the scratch deck
recipe rely on. When the state IS refused, `config.scratch_root` puts the scratch where the
refused board is not: the root it was pointed at, unless that root's own `state/` is the
board being kept away from, in which case the checkout the running code lives in.

So `python3 <worktree>/bin/kb create` with `KEEL_HOME=<live>` files on the WORKTREE'S board,
because that `kb`'s package is the worktree's, and `python3 <live>/bin/kb create` run from
inside that same worktree still files on the live board, because that one's package is the
live checkout's. The absolute path a house's brief hands it is the whole difference.

| Wants the live board | How it gets it |
|---|---|
| The live checkout, on either machine | Nothing: its `state_dir` is inside its own root, so it resolves as it always has |
| A house | The live checkout's `kb` by absolute path, which its brief names |
| A test, or a scratch deck (`<install>/history/tests/live_deck.md`) | `KEEL_CONFIG`, or a path handed to `config.load`: a named toml is taken at its word |
| Anything else, deliberately | `KEEL_LIVE_STATE=1`, the one override, which no house is handed (`childenv.WITHHELD`), and a Keel house's brief says is not its to set |

## How to change it

The Atlas is the source of truth. Read the page for a component before you change it, and
update that page in the same commit. `tests/test_atlas.py` fails when the Atlas and the
code disagree about a module, a script, a verb or a config key, so a rename that skips the
page does not merge. Where a page and the code genuinely disagree, the code wins and the
page is the bug.
