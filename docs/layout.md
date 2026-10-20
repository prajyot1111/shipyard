# Layout and contracts

The parts of Keel, the boundaries between them, and the data every part reads. A builder
working on one part must not change another part's contract without changing this file in
the same commit. The plan that says why is history, in the install (`<install>/history/docs/plan.md`);
this file says what.

## Directory layout

    bin/keel                launcher: `keel <role>` (drain | serve | fetch | run) and `keel <verb>`
    bin/kb                  the board CLI, same as `keel kb ...`
    bin/keel-turn-end       the turn-end half of a house's Stop hook (keel/ending.py)
    keel/config.py          config loader (the install's config.toml); resolved paths; the space table
    keel/board.py           the store: schema, writes, stage refusals, approve, split, hooks
    keel/views.py           the derived dict attached to every card read (gates, needs_you, startable, backlog)
    keel/cardspec.py        the card defaults: one resolver every create goes through, provenance, readback
    keel/models.py          the model names Keel passes to `claude --model`, and its own turns' models
    keel/sessionorigin.py   the csr sidecar a house launch writes, naming the card
    keel/importer.py        the one-time fold of Harbor's ledger into the board (`kb import-harbor`)
    keel/cli.py             one table of verbs: argparse, the dispatch and `kb help` all read it
    keel/harness.py         the only place that runs the `claude` binary
    keel/house.py           brief assembly, per-house settings file, worktree via adapter
    keel/trust.py           a house's cwd trusted in the space's .claude.json before it starts; forgotten when reaped
    keel/prompts.py         the resume prompts for the plan gate, and the brief's "What you can do"
    keel/ending.py          the turn-end Stop hook: the record at the outcome gate, the discussion flag
    keel/drain.py           the drain role: claim, start, reconcile
    keel/trackclose.py      a tracking card whose slices are all done closed by the drain, its rollup the outcome (lane X, c-649)
    keel/login.py           whether a space's login works: its lost-login words, one probe, state/login.json
    keel/loginhold.py       a card the drain held for its space's expired login, and its comeback
    keel/machine.py         available memory, the process table and renice, for the drain's box limits
    keel/doctor.py          `keel doctor`: resolved config, claude, board counts; exit 1 on anything missing
    keel/install.py         `keel install`: writes the engine's plist or systemd unit, loads it only with --load
    keel/service.py         one service as a launchd plist or a systemd user unit (+ timer): write, load, state, restart, unload
    keel/boardlist.py       the deck's board list with each board's card, and the search across board files
    keel/boardgrammar.py    the board grammar's version, its generated card, the previous grammar's translator
    keel/serve.py           the serve role: the HTTP door (routes, static page, segment apps, lavish proxy + revive)
    keel/deckstate.py       the state document `GET /api/state` returns, and one card's detail
    keel/actions.py         `POST /api/action`: every deck verb, carried out through kb, house, harness or the adapter
    keel/openapp.py         Resume and open in app: the house woken with no turn, and its current claude.ai link
    keel/artifacts.py       HMAC artifact tokens, the roots and the credential denylist, a small markdown
                            renderer, and the lavish surface lookup
    keel/atlas.py           docs/atlas: the page index and one page rendered for the deck
    keel/fetch.py           the fetch role: segments' fetch.py under the shared lock, asks to cards
    keel/adapters.py        adapter discovery and invocation
    keel/authority.py       what actor bosun may do (c-522, c-593): its key, the verb allowlist, builder mode, gate checks
    keel/repairhouse.py     Bosun's house repairs: kb console resume/retry --why (c-593, out of the retired drive.py)
    keel/pausewake.py       the drain's wake of Bosun for a house auto mode paused (c-584, c-593)
    app/                    the deck page (no external resources): index.html, ui.css, manifest.json,
                            sw.js, and the script modules ui.core.js (state, helpers, routing,
                            chrome), ui.findcore.js, ui.findpages.js, ui.find.js and ui.find.css
                            (the find bar on every list), ui.tips.js (every card action's hover line and its group), ui.modal.js (the card dialog), ui.cards.js (the list, the
                            kanban, the inspector), ui.reviews.js (the two adapter routes),
                            ui.views.js (the other routes), ui.atlas.js (the Atlas), ui.boardlayout.js,
                            ui.board.js, ui.boardlist.js, ui.boardfull.js and ui.boardcallout.js (the
                            board's layout choice, the board, its list, its full screen, the
                            walk's callout) and ui.js (the
                            boot and the render pass). Every one of them is in serve's APP_FILES
    keel/packkit/           the pack kit (c-735): what every code host pack shares (the card,
                            the cut, the drafts, Ship, sight, review cards, the brief, the verbs,
                            the requirement rows, the guard and its reader), the host layer
                            contract (layer.py), two transports (cli.py, rest.py) and the
                            conformance suite (world.py, standin.py, conformance.py,
                            lifecontract.py)
    keel/packcheck.py       `keel pack check <dir>`: a pack's suite, and the contracts it must hold
    keel/scaffoldkit.py     `keel new pack <name> --kit`: a code host pack on the kit
    packs/<name>/           a pack: its adapter executables (worktree, brief, pr, publish, act),
                            options.json, providers/<route>, pack.toml; an install's own packs
                            are <install>/packs/<name>/ (adapters/<name> is the older link to one).
                            The tree ships sandbox (the example), github and gitea (code hosts
                            on the kit: a host layer, its checks, its guard policy, shims)
    etc/house-contract.md   prepended to every house brief (under 60 lines)
    etc/space-personal.md   appended for personal houses
    etc/space-work.md       appended for work houses, before the adapter's brief
    etc/*.plist             launchd agents, installed by `keel install`
    state/                  gitignored. board.db, cards/<id>/, logs/, worktrees/, human.token
    tests/                  unittest, `make test`
    docs/

## config.toml (the install's; the shipped example is etc/shipyard.example.toml)

    [keel]
    state_dir = "~/keel/state"
    houses_max = 3
    reviews_max = 2                         # the review pool: cards whose options.slot is "review"
    poll_seconds = 30
    drain_paused = true                     # the safety catch until cutover; defaults to true
    backlog_days = 7                        # days at the outcome gate before a card backlogs
    segments_dir = "~/harbor/segments"      # until cutover
    fetch_lock_dir = "~/harbor/ledger"      # optional; defaults to <segments_dir>/../ledger, Harbor's lock dir
    serve_port = 8790                       # the deck; 8791 while the old dashboard still holds 8790
    lavish_port = 4387                      # what the deck proxies to, and revives when it is down
    lavish_state = "~/.lavish-axi/state.json"   # optional; lavish's own session file, for plan_live
    discussion_idle_seconds = 1200          # a plan discussion ends after this long with nothing sent
    host = "mac"                            # the name the deck's drain pill shows for this machine
    artifact_roots = [                      # trees the deck may serve a file from, beyond the two implicit ones
      "~/harbor/artifacts", "~/.claude/plan-archive", "~/.claude/plans",
      "~/.claude/pr-watch/context", "~/.claude/pr-reviews", "~/workspace/lavish-artifacts",
      "~/workspace/cloud-worktrees", "~/workspace/webapp-worktrees",
    ]

    [spaces.personal]
    config_dir = "~/harbor/spaces/personal/.claude"   # until cutover
    repos = { harbor = "~/harbor", keel = "~/keel" }
    contract = "etc/space-personal.md"
    deny = ["mcp__claude_ai_Slack", "mcp__claude-in-chrome"]
    model = "opus"                          # a card here that names no model gets this one
    confirm = ["repo", "model"]             # fields never filed silently (the create readback)

    [spaces.work]
    config_dir = "~/.claude"
    repos = { cloud = "~/workspace/cloud", "webapp-react" = "~/workspace/webapp-react" }
    contract = "etc/space-work.md"
    adapter = "work"
    deny = ["mcp__claude-in-chrome"]
    model = "opus"
    confirm = ["repo", "autonomy", "design_doc", "base", "tracker_mode"]

    [models]                                # Keel's own model turns
    converse = "opus"                       # the voice conversation
    refine = "sonnet"                       # the one turn per capture

`artifact_roots` is where a card's `plan_ref` and `output_ref` are allowed to point: paths
are absolute with `~` expanded, `state/cards/` and `segments_dir` are always allowed on top
of them, and the credential denylist applies inside every root. Adding a root is a config
change, never a code change, which is the point: the tools that write plans put them in
their own places and a new one must not need a release.

`config_dir` becomes `CLAUDE_CONFIG_DIR` for every house in that space; that is the whole
credential boundary. `repos` maps a card's `repo` to a checkout the adapter (work) or
`git worktree` (personal) cuts from. While `drain_paused` is true the drain reconciles but
starts nothing on its own; `keel drain --once --card <id>` still starts that one card.

## The card

SQLite, `state/board.db`, three tables, WAL mode, every write in a transaction. Columns added
after the first schema (`topic`) are listed in `board.MIGRATIONS` with their `ALTER TABLE`,
and `Board.__init__` applies the ones the file lacks, so an older board migrates on open.

    cards(
      id TEXT PRIMARY KEY,              -- c-NNN, continuing Harbor's numbering after import
      space TEXT NOT NULL,              -- work | personal, immutable after create
      title TEXT NOT NULL,
      brief TEXT NOT NULL DEFAULT '',
      autonomy TEXT NOT NULL DEFAULT 'autonomous',   -- attended | autonomous
      repo TEXT,                        -- key into spaces.<space>.repos, or a comma list for cross-repo; NULL = errand
      model TEXT,                       -- filled at create (keel/cardspec.py); a NULL left by an import blocks at launch
      stage TEXT NOT NULL DEFAULT 'inbox',  -- inbox | assigned | planning | building | review | shipping | done
      blocked_reason TEXT,              -- a flag; NULL means not blocked; the card keeps its stage
      session_id TEXT,                  -- the house's Claude Code session uuid, as the harness reports it
      plan_ref TEXT,                    -- path or URL, outside every worktree
      output_ref TEXT,                  -- PR URL, artifact path, or file
      parent TEXT,                      -- the big card this slice came from
      after TEXT,                       -- the sibling slice this one waits for
      topic TEXT,                       -- a free grouping word for the deck (the composer infers it; kb set changes it)
      options TEXT NOT NULL DEFAULT '{}',   -- JSON; schema declared by the space's adapter (options.json)
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)

    events(
      id INTEGER PRIMARY KEY,
      card TEXT NOT NULL,               -- a card's id, or a request's (r-N) or an ask's (a-N) for its own events
      at TEXT NOT NULL,
      kind TEXT NOT NULL,               -- create | set | stage | note | hook | session | resume | block | unblock | split | approve | claim | relay | carried | correct | mark | reply | request | ask
      actor TEXT NOT NULL,              -- human | drain | house | hook | serve | fetch | import | voice | bosun | doctor
      text TEXT, data TEXT)             -- data is JSON

    requests(                           -- Bosun's requests (c-520, keel/requests.py); not cards
      id TEXT PRIMARY KEY, n INTEGER NOT NULL UNIQUE,   -- r-N
      actor TEXT NOT NULL, card TEXT,   -- who filed it, and the card it is about
      what TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
      key TEXT,                         -- the fingerprint a sighting folds by (drain, doctor)
      seen INTEGER NOT NULL DEFAULT 1, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      state TEXT NOT NULL,              -- sighted | open | taken | resolved
      taken_by TEXT, how TEXT,          -- fixed | filed | declined | escalated
      gap TEXT, note TEXT, filed_as TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)
    -- its moves are `request` events whose `card` is the request's id

    asks(                               -- Bosun's questions for the user (c-521, keel/asks.py); not cards
      id TEXT PRIMARY KEY, n INTEGER NOT NULL UNIQUE,   -- a-N
      kind TEXT NOT NULL,               -- approval | decision | escalation
      actor TEXT NOT NULL, card TEXT,   -- who raised it, and the card it is about
      question TEXT NOT NULL, why TEXT NOT NULL,
      options TEXT NOT NULL,            -- JSON: [{letter, label, does, files?}], A is Bosun's recommendation
      state TEXT NOT NULL,              -- open | answered | redirected | withdrawn
      answer TEXT, words TEXT, message TEXT,   -- the letter, the user's words, the user's chat message
      channel TEXT,                     -- tap | voice | chat
      answered_by TEXT, answered_at TEXT, filed_as TEXT,
      delivered_at TEXT, delivered_by TEXT,    -- when Bosun was told: wake | hook | chat
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)
    -- its moves are `ask` events under the ask's id, and on the card it is about

Derived, never stored:

- **plan gate open**: `stage = planning and autonomy = attended and plan_ref is not null`
- **outcome gate open**: `stage = review`
- **notice**: `options.notice_key` is set and `stage != done` (a segment's notice)
- **gate since**: `derived.gate_since`, the instant the wait on the user opened (block, plan gate,
  outcome gate, notice, in that order), read off the event that opened it; null otherwise
- **needs you**: plan gate open, or outcome gate open, or `blocked_reason is not null`, or notice,
  or an open ask about the card (c-521);
  never for an archived or backlog card
- **kind**: `repo is null` means errand (restricted tools, no worktree); otherwise a house with a worktree
- **worktree path**: the adapter's answer (work) or `<state_dir>/worktrees/<id>` (personal repos);
  a cross-repo card's further repos get `<state_dir>/worktrees/<id>-<repo>` and are `--add-dir`s
- **backlog**: `stage = review` and the newest `stage` event that moved the card there is
  older than `backlog_days` (an imported card has no stage events, so its `created_at` is
  the date: the fold gave every imported card the same `updated_at`, the ledger's last bulk
  write). Date alone, plus the user's manual move, nothing else: no cap, no ordering, no rank.
  `options.backlog` overrides the date outright in either direction, `"backlog"` always and
  `"active"` never, until `kb backlog <id> auto` clears the key. Only a card at its outcome
  gate can backlog, so a plan gate never does, and a tracking card does only once it is at the
  outcome gate every slice being done brings it to (lane X). A backlog card is not `needs_you`, `kb needs-you` and the deck's Attention
  and Now leave it out, and the card carries `derived.backlog` and `derived.backlog_override`
- **backlog since**: `derived.backlog_since`, the instant the card entered its outcome gate
  and the one the backlog rule measures from: the newest stage-to-review event, or an
  imported card's `created_at`. It is set on every card at its outcome gate, backlogged or
  not, so the deck can say how long ("at review 41 days"), and null anywhere else. Not
  `updated_at`, which any later note or set moves
- **in a discussion**: `options.discussion` is true, set when the human sends a plan back
  with `stay` and cleared by the card's turn-end hook when that turn ends. The card is at
  planning with its gate open throughout; the deck reads this key, nothing derives it
- **record nudged**: `options.record_nudged` is true once the turn-end hook has sent a house
  back for a thin record at the outcome gate, so that nudge can never fire twice for a card
- **archived**: `options.archived` is true. An archived card is never `needs_you`, never
  `startable`, never reconciled by the drain, and `kb list` hides it unless `--all`
- **parent stage**: a card with children is at `review` when any child is, else `building`; when all are done it is `review` until the drain closes it (or the user's Approve outcome, while it waits at review), then `done` (lane X, 2026-09-24; c-649)
- **startable**: `stage = assigned and blocked_reason is null and (after is null or after's stage in (review, done))`
  (`after`'s stage is its derived one when `after` is itself a parent)
- **tracking card**: a card with children. Its stored `stage` is left where the split found it;
  `kb stage` refuses it and it is never startable. Its children carry the gates, until every
  one is done: then the drain closes it to `done`, publishing nothing, with a rollup of its
  slices as its outcome (`outcome.md`), and reopens it if a slice leaves done (lane X,
  2026-09-24; c-649, `keel/trackclose.py`).

Card folders: `state/cards/<id>/` holds `plan.html` or `plan.md`, `context.md`, `assets/`,
`settings.json` (the house's hooks file), `brief.md` (what the house was given), and on a
tracking card `outcome.md` (its rollup, written by its close, c-649).
`context.md` starts with six headings: Where it stands, What is next, Why this shape,
Open questions, Evidence, PR body. The sixth is where a work house stages the pull
request description; the work pack's `pr` (`<install>/packs/work/pr`) posts that section verbatim (everything from the
heading to the end of the file, since the body has sub-headings of its own).

## kb verbs

All verbs print JSON with `--json`, human text otherwise, and exit non-zero with a one-line
reason on refusal. `--actor` defaults to `house` when `KEEL_CARD` is set in the environment,
`human` when `KEEL_TOKEN` matches `state/human.token`, else `cli`.

    kb create --space S --title T [--brief B] [--autonomy A] [--repo R] [--model M]
              [--parent P] [--from F] [--after A] [--topic T] [--option k=v ...]
              [--assumed field,...]        -> prints the id, says the readback on stderr
              (--json carries it as `readback`); unset fields resolve through keel/cardspec.py
    kb list [--space S] [--stage S] [--topic T] [--needs-you] [--backlog] [--all] [--json]
              --backlog is only the backlogged cards; --all includes archived ones; the default
              text marks a backlogged card with a `backlog` tag
    kb show <id> [--json]
    kb set <id> field=value ...          (space is immutable; stage goes through `stage`; `topic=` and
                                          `options.k=v` are ordinary fields; slices inherit the parent's topic).
                                          `options.k=null` REMOVES that key rather than storing a null, so a
                                          key handed back to its default leaves exactly the JSON the verb that
                                          owns it leaves (`kb backlog <id> auto`, and the deck's own `set`)
    kb stage <id> <stage> [--plan REF] [--output REF] [--note ...]
              refusals: attended card may not leave planning without approve;
              review requires plan_ref (any card) and output_ref; done only from review or
              shipping; shipping is entered only by approve (or from done, drain or human)
              and left only by the drain or the human (lane SHIP)
    kb approve <id> plan|outcome          human only (token); plan: planning -> building;
              outcome: review -> done, and runs the adapter's publish for work cards; a
              publish answering `"shipping": true` moves it to shipping instead. Bosun
              (its key, c-522) may approve a PLAN only, with --checked, on a console card or a
              driven personal card under the user's grant (`keel/authority.py`)
    kb grant <id> [--revoke]              the user's alone, personal only: options.grant over the card and its tree
    kb note <id> "text"
    kb block <id> "reason"  |  kb unblock <id>
    kb split <id> --slice "title|brief[|after-title][|repo=key[,key]]" ...   creates children, parent becomes tracking
    kb needs-you [--space S] [--backlog] [--json]     backlog cards are hidden unless --backlog
    kb backlog <id> [backlog|active|auto]   the manual override of the date rule, recorded as a
              `set` event; `auto` (the default) clears it back to the date
    kb help [<verb>]      one line per verb, `<verb> <usage>: <what it does>`, in the order the
              cli defines them, with exactly one `: ` per line; `kb help <verb>` prints that
              verb's full usage. Both come from `cli.VERBS`, the same table argparse is built
              from and the dispatch reads, so the house brief's "What you can do" block can be
              generated from it and cannot drift
    kb event <id> --hook <Stop|SessionEnd|Notification>     reads the hook JSON on stdin, records it
    kb stop-check <id>     the Stop hook body: reads stdin; if the card is at building with no
                           stage move and fewer than 2 prior blocks, prints
                           {"decision":"block","reason":"..."} and records the block; else prints nothing.
                           The third Stop at building sets `blocked_reason` (the house is done nudging)
                           and prints nothing, so Needs you shows it.
    kb import-harbor [--ledger ~/harbor/ledger/cards.jsonl]   idempotent, keeps ids and timestamps
    kb session <id> --set <uuid> [--transcript PATH] [--bg-id ID]   record the house session the harness minted

## keel/harness.py

The only module that runs `claude`. Recorded output from a real probe is in
`tests/fixtures/harness/` (read its README first); tests run against those recordings.

    start_bg(cwd, prompt, *, name, config_dir, settings_path, model=None, add_dirs=(),
             restricted=False, tools=None, permission_mode="auto") -> {"bg_id": "083b13ff", "session_id": "<uuid>"}
        runs `claude --bg --name <name> --permission-mode auto --permission-prompts none
        --settings <file> --disallowed-tools "Agent(fork)" [--model M] [--add-dir ...]
        [--restricted --tools ...] "<prompt>"` with CLAUDE_CONFIG_DIR=config_dir,
        KEEL_CARD=<name> and KEEL_HOME in the environment and `<KEEL_HOME>/bin` first on
        PATH (`name` is the card id; the drain counts houses by it); parses the short id from
        `backgrounded · <id> · <name>`; resolves the full session uuid from agents() by name,
        polling for about five seconds, and keeps the short id if the row never appears.
        `--bg` manages the session id itself, so Keel never passes `--session-id`. The
        prompt goes before `--disallowed-tools`, `--add-dir` and `--tools`: those are
        variadic and would take it as one more value.
    agents(config_dir=None) -> list of rows as recorded in tests/fixtures/harness/agents.json;
        a listing sees only the sessions of the config dir it runs under
    agents_across(config_dirs) -> the union over the spaces' config dirs, one row per session
    find(session_id, rows=None) -> the agents() row (full uuid or short id) or None
    logs(bg_id, config_dir=None) -> str with ANSI stripped
    last_said(transcript_path, n=40) -> the last assistant text lines from the jsonl transcript
    stop(bg_id, config_dir=None)
    login_probe(config_dir, *, cwd, timeout) -> CompletedProcess
        `claude -p "Reply with the single word ok." --no-session-persistence --model haiku
        --strict-mcp-config --tools ""` under the space's config dir, never with the user's token,
        in its own process group (`keel/login.py` reads the answer)
    resume_bg(session_id, prompt, *, cwd, config_dir, settings_path, name=None, model=None,
              add_dirs=(), restricted=False, tools=None) -> {"bg_id", "session_id"}
        runs `claude --resume <session_id> --bg --name <name> ...` with the same flags as
        start_bg, so the resumed house keeps its name, model and confinement. The
        conversation continues but the harness mints a new session uuid, which
        `house.resume` records on the card (recorded, not assumed: fixtures README)

Facts the drain relies on (all recorded, not assumed): the Stop hook fires at every turn
end and its `{"decision":"block","reason":...}` answer makes the session continue;
SessionEnd fires when the process ends, including on `claude stop`; a stopped session
disappears from `agents()` (it is listed only with `--all`, status null); the Stop payload
carries `last_assistant_message` and every payload carries `transcript_path`, so `kb event`
stores both on the card's events and the drain uses them (falling back to `last_said` on the
transcript) when it blocks a card.

## keel/house.py

    settings_for(cfg, card) -> writes state/cards/<id>/settings.json (kb by absolute path):
        hooks.Stop        -> `<KEEL_HOME>/bin/kb stop-check <id>` and
                             `<KEEL_HOME>/bin/keel-turn-end <id>`, two commands in one group:
                             the nudge budget at building, then the record at the outcome
                             gate and the discussion flag (`keel/ending.py`)
        hooks.SessionEnd  -> `kb event <id> --hook SessionEnd`
        hooks.Notification (matcher idle_prompt|permission_prompt) -> `kb event <id> --hook Notification`
        hooks.PreToolUse (Bash, mcp__docker__.*) -> ~/.claude/hooks/guard-stack-invariants.py,
                          only when that file exists
        permissions.deny  -> the space's deny list
        permissions.allow -> the space's allow list, for a house with an open shell (a repo
                             card, except a fork's review card), when the space names
                             one; a deny still wins
        env               -> KEEL_CARD=<id>, KEEL_HOME, PATH with <KEEL_HOME>/bin first. The
                             process environment does not reach a house (`--bg` claims a
                             pre-spawned daemon process); the settings env does.
    brief_for(cfg, card) -> etc/house-contract.md + "What you can do" + the card block
                       + the space contract + (work) the adapter's `brief <card>` output;
                       written to brief.md, and context.md is created with its six headings
                       if missing. "What you can do" is generated (`prompts.abilities`): the
                       board's verbs from `kb help`, run with the house's own environment and
                       filtered of the verbs a house must never call (approve, anything named
                       like stop, import-harbor, drain, serve, fetch, run, install), the
                       child-card form (`kb create --parent $KEEL_CARD --after <id>`), and a
                       dozen lines on what the human can see from the deck. A `kb help` that
                       exits non-zero falls back to a short hand-written list, noted in the
                       drain's log
    worktree_for(cfg, card) -> the adapter's `worktree <card>` (work) or git worktree add (personal),
                          recreating from the existing branch when the directory is gone
    launch(cfg, board, id) -> worktree, settings, brief, harness.start_bg, `session` event, then
                          stage planning (attended) or building (autonomous) if still at assigned.
                          A start that fails blocks the card with the reason.
    resume(cfg, board, id, prompt=prompts.RESUME)   # "continue from where you stopped; the card is still at <stage>"
                       -> harness.resume_bg with the same settings file; records `resume`

The card block in the brief is a short fenced JSON of the card's fields (id, title, brief,
autonomy, repo, model, stage, plan_ref, options) plus `KEEL_CARD=<id>` and `KEEL_HOME` in
the environment (through the settings file's `env`). An errand (`repo` null) runs in `state/cards/<id>/` with `--restricted
--tools Read,Write,Edit` unless `options.tools` names the tools, and `options.add_dirs` (a list
of paths) become its `--add-dir`s: that is how an ask card reaches its segment's `data/`.

## keel/drain.py (role `drain`)

Every `poll_seconds`:

1. `agents = harness.agents_across(every space's config_dir)`
2. For every unarchived card with a `session_id` at building, or at planning with no
   `plan_ref` yet (the house died before delivering its plan): if no agent carries that
   `sessionId`, the house has exited. If this card has no `resume` event yet, resume it
   (`harness.resume_bg`) and record `resume`; otherwise `block` with what it last said: the
   `last_assistant_message` of the newest Stop event on the card, else `last_said` on the
   transcript the hooks recorded, else the last 40 lines of `harness.logs`.
3. Unless `drain_paused` (then only a card named with `--card`): walk the startable cards
   of the spaces this machine serves, oldest first, and start each one whose POOL has room:
   cut its worktree, write settings and brief, start it, record its session, and stage it
   `planning` (attended) or `building` (autonomous). There are two pools and they fill
   independently. A card whose `options.slot` is `review` counts against `reviews_max`;
   every other card counts against `houses_max`. A pool is counted from the agents rows
   whose name is a card id at planning or building, plus what this pass started or resumed
   in it. A full pool is passed over, not a stop: the next card in the other pool still
   starts, so a review never takes a build slot and a queue of reviews never holds up a
   build. The pass logs one line carrying both counts (`houses=` and `reviews=`).
4. A card at `review`, or at `planning` with its plan gate open, is never touched, whatever
   its session is doing.

No other rule. No timers on quiet, no pane reads, no stop. `run` logs one line per pass to
`state/logs/drain.log` and never lets a pass's exception out of the loop.

## keel/serve.py (role `serve`), with deckstate, actions and artifacts

Stdlib `http.server` (threading), bound to 127.0.0.1:`serve_port`; the tailnet fronts it.
`keel serve [--port N]` and `keel run --roles serve` run it. Reads are cached for three
seconds; a write drops the cache.

    GET  /, /ui*.js, /ui.css, /manifest.json, /sw.js  app/ (APP_FILES), never cached
    GET  /api/state                the state document (below)
    GET  /api/health               {level, reasons, services}: keel/health.py's verdict and the
                                   services block, never a 304 (the verdict does not move the
                                   state's revision)
    GET  /api/card/<id>            {card, events (all), context, pr_body, stands, plan_text, children}
    GET  /api/atlas                {pages: [{slug, title, summary, order, present}]}, from
                                   docs/atlas/index.json, which is the allowlist
    GET  /api/atlas/<slug>         {slug, title, html}: that page through `markdown_html`, body
                                   fragment only, with a link to a sibling page rewritten to
                                   `?view=atlas&page=<slug>` so the reader stays on the deck
    POST /api/action               {"verb": ...} -> {"ok": true, "result"} or {"ok": false, "error"} (409 on a refusal)
    GET  /api/artifact/<token>     a file under one of the artifact roots, by a token this server minted;
                                   a markdown file is rendered to a page unless `?raw=1`
    GET  /segments/<name>/app/...  the segment's own app, path traversal refused
    anything else                  proxied to lavish on lavish_port, streamed, with the Origin rewrite:
                                   the browser's claimed origin is compared against our own Host and only
                                   on a match lavish is handed `http://127.0.0.1:<lavish_port>`.
                                   A connection failure on a request a person makes (`GET /session/<key>`,
                                   `GET /events/...`, `POST /api/...`) starts lavish once and retries once

**The state document** (`deckstate.build`): `now`; `cards` (every card with `derived`
(including `backlog`, `backlog_override` and `backlog_since`), plus
`last_event`, `last_said` (the newest Stop hook's message, for live, blocked and review cards),
`links` {plan, plan_live, output, context, and the adapter's story/pr/design_doc}, `house` (the agents row
joined by session id or by name, for live and blocked cards), `children`); `needs_you` and
`running` (ids, neither carrying a backlog card); `backlog` (the backlogged ids, for the deck's
own chip); `houses` (ids the Now strip shows: a listed house, or blocked with a session, never a
backlog card);
`drain` {host, at, age_seconds, text, alive} from the last `drain:` line of `state/logs/drain.log`
(`host` is the config's `host` unless the line carries `host=`); `usage` from
`~/.claude/helm-usage-limits.json` (`KEEL_USAGE_FILE` overrides; two windows with used percentage,
reset time and the file's age); `segments` (each `<segments_dir>/<name>/summary.json` plus
`has_app` and `app_url`); `spaces` (per space: adapter, repos, `options` = the adapter's
options.json or the built-in personal subset repo/autonomy/model, `verbs` = `act verbs`,
`topics` = the distinct topics on its unarchived cards, for the Cards group-by, `counts` =
{cards, needs_you, backlog} over the same cards, which is what a filter chip shows a number
from);
`providers` (per space with an adapter: each `providers/<route>` output); `config`.

**Actions** (`actions.act`), one verb per body: the kb verbs `create` (`start: true` also stages
`assigned` and, while the drain is paused, runs `keel drain --once --card`), `set` (`fields`,
`options.k` allowed), `stage`, `approve`, `note`, `block`, `unblock`, `split` (`slices`),
`session` are `bin/kb <verb> ... --json` run as a subprocess with `KEEL_TOKEN` from
`state/human.token` (and `KEEL_CONFIG` when the config came from a file), so the board records
them as `human`. The three gate verbs carry the human's answer to the house and are the deck's
only way to answer a gate: `approve` {id, gate} is the kb verb, and at the plan gate it then
resumes the house with `prompts.approve`; `sendback` {id, reason, stay} notes the reason and
resumes with it (at the outcome gate it also stages `building`; with `stay` it is a discussion:
`options.discussion` is set, the card stays at planning with its gate open, and the prompt is the
poll, reply, poll loop bounded by `discussion_idle_seconds`); `end_discussion` {id} runs
`lavish-axi end <plan_ref>` so the house's own poll returns and its loop ends naturally, and says
so honestly when lavish is unreachable (it never stops a session). Each gate verb returns
{card, prompt, resumed, note}. A plan that is an `.html` file is a lavish surface, so its prompts
open with one bounded `timeout 20 lavish-axi poll <plan>`: annotations are collected on resume,
because a house that waited for them would hold a slot for nothing.
`house.resume` {id, said?} calls `house.resume` (and unblocks a blocked card), with `said`, the user's answer to a blocked house, quoted into the prompt by `prompts.answer_resume` and noted on the card once it has gone;
`house.retry` unblocks, stages `assigned` and runs one explicit drain pass; `house.stop` is
`harness.stop` by the recorded bg id, the only stop in the system, noted on the card;
`house.logs` returns the tail; `dropin` cannot open an interactive session from a server, so it
recreates the placement and returns the exact `cd ... && claude --resume` command, noting it;
`adapter` {space, route, action, key, args} runs `adapters/<name>/act do <route> <action> <key>`
with `args` as JSON on stdin. A refusal is one line in `error`.

**Artifacts** (`artifacts`): a token is the absolute path plus an HMAC (key
`<state_dir>/artifact.key`, 0600, created on first use), minted only for a file under one of
the roots (`state/cards/`, `segments_dir`, and every `artifact_roots` entry) that is not a
credential by directory, name or suffix (`.ssh`, `secrets`, `.env`, `id_rsa`, `human.token`,
`*.key`, `*.pem`, ...), and checked the same way again before a byte is served. A URL is
passed through as is; a directory holding `index.html` resolves to that file.

`markdown_html(text, title, base_dir, cfg)` renders headings, fenced code, lists, rules and
paragraphs, and turns `![alt](path)` into an `<img>` and `[text](path)` into a link when the
path (relative to `base_dir`, the document's own directory, or absolute) passes those same
rules. The `src` and `href` are always a token this server minted, never a string from the
document, which is escaped first; anything that fails renders as its words in a muted span
whose title says why. Absolute http links are left alone.

`lavish_surface(cfg, path)` is the live surface for a file lavish still has a session for,
read from `lavish_state` (lavish's own `sessions` map of key, file and status, which
outlives the server). It is a path on the deck's origin (`/session/<key>`), never lavish's
own loopback URL, because the phone is not this Mac. `serve` starts lavish when a person
asks for a surface and nothing answers: once, detached, with the process kept and waited
on, a twenty second cooldown after a failure, and an honest 503 when it will not come up.

**The page** (`app/`): one page; routes are
`?view=now|attention|cards|segments|atlas|reviews|prs|more` with `&page=<slug>` on atlas and
with `&card=<id>` (the detail beside the list on the desk, a full-screen route on the phone),
`?space=` and `?d=` pin the palette and density. The desk has the rail and the Work | Personal
switch, the Glance | Work | Deep dial and the New card button; the phone has the five-item dock
and the same views. Six script modules, in load order: `ui.core.js` (state, helpers, the state
document, routing, the rail, header, controls and dock), `ui.modal.js` (the card dialog),
`ui.cards.js` (the Cards list, the kanban and the inspector), `ui.reviews.js` (the Reviews
route: the scanner bar, the list, the lanes, and the PRs route beside it), `ui.views.js`
(Now, Attention, Segments, More) and `ui.js` (the boot and the one render pass). They share
`window.Keel`; a name is read at call time, so the order only has to put the boot last.

Every list honours the space switch. Cards, the board list and Reviews
are found through ONE find bar (`ui.findcore.js`, `ui.findpages.js`, `ui.find.js`; the deck's
Atlas page, "The find bar"): search with typed `field:value` filters, a multi-select Filter
panel with counts and the Include switches, Sort, View (Cards: the table or the seven-lane
kanban, grouped by none, stage, `spaces.<name>.topics`, parent or repo) and saved Views, all
in the URL and remembered per page. A backlog card's detail moves
it with the `set` verb (`options.backlog` = `backlog` | `active` | null for the date rule again),
because the deck has no backlog verb of its own.

**A card's state is THREE WORDS**, not dots: `house`, `plan` and `outcome`, one function each in
`ui.cards.js` (`houseWord`, `planWord`, `outcomeWord`) and the single place those rules live, so
the table, the kanban tile, the phone list, the inspector's head, a slice list and Now all say
the same thing about one card. Every word is derived on the page from the state document:

- **house**: `blocked` (`blocked_reason`), `talking` (`options.discussion`), `working` (a live
  `house` row with status busy), `idle` (a live row that is not), `none` (no row at all), in that
  order, and the sibling a slice is still waiting for rides beside it ("waits for c-xxx").
- **plan**: `none` (no `plan_ref`), `gate open` (`derived.plan_gate`), `approved` (the newest
  `approve` event with gate plan when the card's events are loaded, else any stage past
  planning), `written` (a plan_ref and nothing has approved it yet).
- **outcome**: `approved` (stage done), `backlog N d` (`derived.backlog`, counted from
  `derived.backlog_since`), `gate open` (`derived.outcome_gate`), `draft PR #n` or `output`
  (`output_ref`, with `options.pr` when there is one), `none`.

A **tracking card** has no house, plan or outcome of its own, so it says its children instead:
`derived.parent_stage` and "n of m slices done", one cell across all three columns. Grouped by
parent, its slices are drawn indented under it, and a slice whose parent is filtered out stands
on its own. Now collects the running slices of one big card onto that card's tile rather than
drawing them as unrelated houses.

**The card dialog** is the new-card form and the same form editing a card ("Edit" on the
inspector, which sends `set`). It draws every field of the space's `options` in order, honouring
`when` and `default_if`, with a run of checkboxes as one row of toggles; a `story` field is
normalised to the schema's own `normalise` shape, so a bare id, the prefixed id and a full
tracker link all land the same. Typing the title infers the story, the repo, the autonomy and the
kind, from words the schema itself carries. Two optional card fields follow the schema's own:
**Parent** (any unarchived card of the space that is not this one or one of its slices) and
**After** (offered only with a parent: that parent's other children), sent as `parent` and
`after` on `create` and `set`. Enter or Create files to inbox, Create and start also stages
`assigned`. On the phone it is a full-screen sheet.

**The Split dialog** is the same modal in its third mode, opened from the inspector's action row
for any card that is not done and has no children yet. It lists slices, each with a title, a
brief and an optional "after" picker over the slices ABOVE it (the board resolves `after` by
title against the slices already created in the same call), and sends
`{"verb":"split","id":...,"slices":[{"title","brief","after","repo"}]}`, which `actions.split_argv`
folds back into `--slice "title|brief[|after-title][|repo=key[,key]]"`. A card that names
several repos offers them as chips on each slice's row, and a slice sends `repo` only when it
keeps fewer than all of them (c-771). A `|` in a title or a brief, and two
slices sharing a title, are refused on the page: the first would split the argument in two and
the second would make `after` ambiguous. The toast names the ids the split created.

**The inspector** follows the retired dashboard's shape: the gate answers in a sticky row under
the title, then Open story, Open design doc, Open plan, Open output, View context, Resume house,
Drop in and the adapter's card verbs, then the gate's evidence, the details, the house notes
(with a one-line note composer) and the events. A button that cannot act is not drawn: Logs and
Stop session want a live agent row, Resume house a session with no live house, and the links
their own key. Open plan prefers `links.plan_live` and says "(live)". The head carries the card's
three words under its id line; a slice carries "slice of c-xxx", which opens the parent, and a
tracking card carries its slices ("Slices, n of m done"), each with its own three words, its
"waits for c-xxx" when it has one, and a tap that opens it. Split is drawn for a card with no
children that is not done; Assign is not drawn for a tracking card, which is never startable.
The card closes by its ✕, by Escape, by a click on the page behind it, or by Back (selecting
pushes history).

Send back on a gate is the `sendback` verb, asked for with a one-line reason first, with `stay`
for a discussion (offered only on a plan gate whose plan is an `.html` surface; a card with
`options.discussion` shows as talking and offers `end_discussion`). Approve plan is `approve`,
which resumes the house itself; when the answer carries no `resumed`, its `note` is the toast.
Kanban drag-to-move is `stage`, a plan-gate card dropped on building is `approve plan`, a review
card dropped on done is `approve outcome`.

Reviews and PRs are the provider's own lanes drawn as columns: the route's `columns` in their
given order (an empty lane is drawn too, as a drop target), each row in its own `kanbanState`,
which both providers now supply. A tile drags to a lane when one of the row's verbs carries
that lane as its `to`, and the drop runs that verb; a lane no verb names is static. Every verb
is also a button on the tile, labelled with the verb's own `label`.

Every route remembers its scroll position, the page's and each inner scroller's, in
sessionStorage, so the five second poll, a reload, Back and Forward all land where the reader
was; a field carrying `data-fk` keeps its caret through a re-render, and the dialog is never
rebuilt by a poll. The page names no employer or work tool: every such label comes from the
adapter at runtime.

## keel/fetch.py (role `fetch`)

Two tiers, and no other rule.

**Fetchers.** `once(cfg, segment=None, changed_only=False)` runs every `<segments_dir>/*/fetch.py`
(sorted; one segment with `--segment`) with cwd at the segment, under the per-segment lock
directory `<fetch_locks>/.fetch-<name>.lock` holding a `pid` file. That is exactly the protocol
of Harbor's `bin/harbor-fetch-lock.sh`: mkdir is the atomic take; a lock whose owner is dead or
that is older than an hour is cleared with rmdir (never a recursive delete); a lock with no pid
yet is treated as held. `fetch_locks` is `fetch_lock_dir` from the config, else
`<segments_dir>/../ledger`, which is where Harbor's hourly job and minute worker lock while
`segments_dir` is `~/harbor/segments`. Sharing the path is what makes coexistence safe: both
systems may run the same fetcher and neither ever runs it concurrently. A held lock is `skipped`
("another job holds its fetch lock"); a lock directory that cannot be created at all is
`unusable` and reported, never mistaken for busy. The interpreter is the venv beside the
segments tree (`<segments_dir>/../.venv/bin/python`, so Harbor's own) when it runs, tested by
executing it, else `python3`. One failing fetcher (non-zero exit, or 600 s without finishing)
never stops the others, and each segment gets one line in `state/logs/fetch.log`:
`ok  <last output line>`, `FAILED (exit n)` with the output, `skipped`, or `NOT RUN`.
`changed_only` runs only a segment whose inputs moved, the gate `harbor-worker` uses: a file
in `data/inbox/`, or anything outside `data/` and `__pycache__` newer than `summary.json`
(no summary yet counts as changed). The fetchers get the process environment as is.

**Asks.** `asks(cfg, segment=None, board=None)`: each segment with a `worker.md` and files
matching `data/asks/ask-*.json` gets ONE autonomous errand card per segment per pass, unless its
`daily_cap` is spent (that segment's cards created today, found by `options.segment`; the asks
then wait, logged) or its `worker.md` is bad (no known `space`, or a non-integer `daily_cap` or
`timeout`: fail closed, logged, nothing spent). The asks move into `data/asks/taken/` BEFORE the
card exists, so each is consumed exactly once even if the house dies. The card: `space` from
`worker.md`, `repo` null, `stage` assigned, title `<segment>: <n> asks`, `plan_ref` the segment's
`worker.md` (so `review` needs only `--output`), `options.tools` the worker's `tools` (default
`Read,Write,Edit,Glob,Grep`), `options.segment`, `options.asks` (the file names),
`options.add_dirs` = [the segment directory], `options.drop` = the inbox file the house must
write. The brief is the `worker.md` body, then "this run": the taken ask paths (paths, not
contents: asks carry attachments a session with `Read` opens itself), the drop path
`data/inbox/worker-<UTC stamp>.json` and its shape `{"entries": [{"k", "v", "t"}]}`, the rules
(write only the drop, never an ask, no commands or network), and the finish:
`kb stage $KEEL_CARD review --output <drop>`. From there it is an ordinary card: the drain
starts it `--restricted --tools <worker tools>` with the segment as an `--add-dir`, `review` is
its outcome gate, and the next fetch folds the drop in. Every ask goes into the batch card;
there is no live lane. `worker.md`'s `timeout` is validated but not enforced: nothing automatic
ends a live session. Events are recorded with actor `fetch`.

**Loop.** `run(cfg)` runs every fetcher on start and then hourly; every 60 s in between, the
changed-only fetch and then `asks`. A pass's exception is logged and never leaves the loop.
`keel fetch --once` is one full pass (every fetcher, then asks) and prints
`fetch: ok=N failed=N skipped=N unusable=N cards=N`.

**Until cutover** Harbor's own hourly `dev.harbor.segments` and minute `dev.harbor.worker`
keep running, and the shared lock is what makes coexistence safe. Keel's fetch role is not to
be scheduled before cutover: `keel install` writes the plist but loads it only with `--load`,
the human's step. Running `keel fetch` by hand against `~/harbor/segments` writes there the way
Harbor's own jobs do (lock directories under `~/harbor/ledger`, and whatever the fetchers write),
and the ask cards it creates start only when the drain is unpaused.

## Adapters

`adapters/<name>/` is found by `spaces.<space>.adapter`. Executables take the card id and
read the card with `kb show <id> --json`:

    worktree <id>        prints the worktree paths, primary first, one per line (the rest are
                         `--add-dir`s), creating them (and the tracker story at task start,
                         recorded as `options.tracker_ref`) when needed; the branch is named
                         once and kept in `options.branch`, so a recreate reuses it; the
                         primary path is kept in `options.worktree`
    brief <id>           prints the work half of the house brief (worktree and container
                         facts, the story, the card's options, the ending)
    pr <id> [--draft|--body]
                         opens the card's DRAFT pull request from `options.branch` against
                         `options.base` (body: the `## PR body` section of the card's
                         context.md, else a default from the card), records `options.pr`,
                         prints the URL. A house runs this itself, after it has pushed its
                         branch. `[--draft|--body]` is the pack kit's contract: on the kit
                         `--ready` is refused by the verb itself (c-738 r1.F2), and only
                         `publish` marks a draft ready. A pack not on the kit may differ (the
                         work pack and the sandbox still take `--ready`)
    publish <id>         run by `kb approve outcome` (on the pack kit only inside that tap or
                         a Ship, whose nonce Keel hands it, c-738 r1.F3): marks the draft ready, then the tracker
                         transition (the story to Code Review), then one `kb note`; prints a
                         JSON summary the approve event stores under `published`
    act verbs            prints {"card": [{verb, label, when, help}]}: the card-level verbs the deck's
                         inspector offers for this space, with the labels it shows (the deck never
                         names them itself). None today: the old enroll verb went with PR watch
    act links <id>...    prints {id: {story, pr, design_doc}} for the cards that have them
    act do <route> <verb> <key>
                         carries out one deck tap (route `reviews` or `card`; the arguments arrive
                         as JSON on stdin); prints JSON, or refuses on stderr with one line.
                         `reviews` takes the gear's two verbs, `set_auto_review` and
                         `set_review_model` (`{"value"}`), which write the space's live override
                         (`keel/reviewsettings.py`) through `keelbridge`; `card` refuses every verb
    options.json         the per-card option schema the deck's new-card sheet draws: a list
                         of {key, label, type, stored (card|options), options, default or
                         default_if, when}; `when` and `default_if` are `key == value` /
                         `key != value` clauses joined by ` and ` (values unquoted)
    providers/<route>    prints JSON for an extra deck route: `reviews`, the review fetcher's
                         two settings for the Reviews page's gear, and no rows
    keelbridge.py        the work adapter's one door back into Keel: an artifact URL for a
                         file, the plan pages switch, and the review settings, all through
                         `KEEL_HOME`

A provider prints `{route, columns, items, hidden}`. `reviews` carries `settings` and empty
`items` and `columns`: the Reviews page lists review cards, which are board cards.

**`settings`** is `auto_review` and `review_model`, as the machine that holds the space will
read them (the config's `review_auto` and `review_model` for the space, or the gear's
override in `state/review-settings.json`), `models` (the choices the gear may offer: opus
and sonnet), and `verbs`, the route's own two, which take no key, so the deck's `adapter`
verb sends an empty `key` and `act do <route> <verb>` takes one or not. When Keel's config
cannot be read, `auto_review` is left out and `models` is empty, and the deck draws no
control. Lane RETIRE (2026-09-24) removed the rest of what this section used to describe:
the old review scanner's rows, lanes, verbs and settings files, and the pull request
watcher's `prs` route with its lanes and verbs (`<install>/history/docs/decisions.md`, RT-1 to RT-3).

`kb approve <id> outcome` runs `publish` BEFORE the transaction that moves the card to
done (the refusals are checked before and again inside), because the adapter writes to
the board through `kb` and the store is one SQLite file. A publish that fails leaves the
card at review with the adapter's stderr as the refusal. `keel/cli.py` passes
`adapters.publisher(config, space, nonce=, timeout=)`; a space without an adapter gets None. In
a space whose publish is a pack's (`adapters.publishes_through_pack`), Approve outcome, like
`kb ship`, runs inside `cli.publishing_tap`: `Board.mark_publishing` writes the marker (the
digest of a one-use nonce and its time), the nonce goes to the verb as `KEEL_PUBLISH_NONCE`,
the tap's budget (`merging.tap_budget`) is its timeout, and the marker is cleared after. A pack
on the kit checks it (`pulls.in_tap`) and refuses `publish` without it, at every stage (c-738).

**A pack on the kit** (`docs/atlas/62-packs.md`, "The pack kit"). Each executable is a shim
that binds the pack and calls `keel.packkit.verbs.run(<verb>, argv, pack=<its folder>,
layer=<its layer module>)`; the guard calls `keel.packkit.guard.main(argv, pack=<its folder>,
policy=<its GuardPolicy>)`. The pack writes one host layer module (`KIT`, `HOST`, and the
operations `keel/packkit/layer.py` names, each taking a `Repo` and raising only the kit's
errors), its requirement checks and its guard policy, and its `tests/test_conformance.py`
subclasses the contracts its claims call for. `keel pack check <dir>` is the gate.

The work pack is an install's own (`<install>/packs/work/`, in the install's packs repo):
Python modules (`workcard`, `naming`, `cut`, `briefing`, `tracker`, `codehost`, `pulls`,
`optionsheet`, `providers`, `acting`, and the shipping and review modules the Atlas's work
adapter page lists) behind thin executables. Its tests and fixtures live in its own `tests/`,
which the adapters job runs from the install `KEEL_CONFIG` names (`tests/packsuites.py`).

## Roles and processes

`keel run --roles drain,serve,fetch` is one process (the laptop today): each role runs its
loop on its own thread (an unknown role is refused). `keel install` writes `etc/dev.keel.plist` with those roles
(KeepAlive, RunAtLoad, `KEEL_HOME`, a PATH that reaches `claude` and `python3`, logs under
`state/logs/`) and loads it only with `--load`. On the VPS split, each machine
runs the roles it serves; `kb` gains `KEEL_URL` and becomes an HTTP client (phase 7).

## Tests

`make test` runs the core suite and the modules the change reaches (`tests/selector.py`),
the packs' own suites when the change reaches them (the tree's `packs/<name>/tests` and,
when `KEEL_CONFIG` names an install, the install's own packs, `tests/packsuites.py`), and the
drift check, which fails if a pack's terms appear outside it or the public check finds one
install's names. Harness tests run against recorded `claude` output in `tests/fixtures/`,
never a live session. The live runs by hand are history, kept in the install
(`<install>/history/tests/`): the first real house on the keel repo itself
(`live_house.md`), the first real work card (`live_work_card.md`), and the deck's real
render, with screenshots and contrast, overflow and tap audits at 1440 and 390 (`live_deck.md`).
