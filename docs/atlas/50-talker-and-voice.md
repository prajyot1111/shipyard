# The talker and voice

The talker is Harbor: one long-lived Claude Code conversation, reachable from a phone,
that files cards and reads the board and never does work itself. The voice gateway is a
second door onto the same board, through speech, and since 2026-09-17 it lives in this
repo with its own interpreter. Neither is part of the engine; both talk to it through
`kb`.

## The talker

It runs `claude remote-control` in server mode under its own config dir: a plain
long-running process with no terminal, started by launchd and kept alive. On Linux a
systemd user unit starts it inside a tmux session that is only a host: its output is teed
to the same log and nothing reads the pane.

| Piece | Where |
|---|---|
| Rulebook | the install's `memory/talker/CLAUDE.md` (c-722 landing B, `talker.Paths.rules_src`), the shipped `templates/memory/talker/CLAUDE.md` while the install has none of its own, but only for a memory `shipyard init` seeded from that template, told by its seeding record (`memoryroot.seeded`, r3.F4), never by a shared file name (an owner's own memory gets no rulebook, and `keel talker install` says to run the move); the config dir's `CLAUDE.md` is linked to it by `keel talker install` and at every talker start (`talker.link_rules`), which replace only a missing entry, a dangling link or a link Keel made, and say what they kept (`talkerdirs.rules_note`); a file, or a link pointed elsewhere on purpose, is never replaced |
| Skills | the links the install records in `memory/talker/skills.json` (c-725), made in the config dir's `skills/` by `keel talker install` and at every start (`talkerdirs.link_skills`), never over an entry there |
| Config dir, denies | `spaces/harbor/.claude/`; `settings.json` denies Read of any `human.token` and `house.key` by file name, wherever the config's state dir is (c-711) |
| Working directory | a numbered run dir under `talker/home` (see "The run directory rotates" below) |
| Memory, canonical | the install's `memory/talker/` (c-722, `talker.Paths.memory_src`), the checkout's `<checkout>/talker/memory/` only while the install holds none; the injected path inside the config dir is a symlink to it, made by `keel talker install` and remade for the new cwd on every reset |
| Memory, for a new install | `templates/memory/talker/`: the neutral set `shipyard init` seeds a new install with, once ([Bosun](96-bosun.md), "Where the memory lives") |
| Runtime verbs | `keel/talker.py`, routed from `keel talker <verb>` |
| Service | `dev.keel.talker.plist` in the install's `services/` (`Config.services_dir`, c-722; a checkout with no install, its `etc/`) (Linux: `dev.keel.talker.service`), written by `install`, loaded only with `--load`, through `keel/service.py`; it carries `KEEL_CONFIG` when the config it was installed from is not the checkout's own, and its files then live in that config's state (c-711, "The talker's files move with its config") |
| Runtime files | `state/logs/talker.log`, `state/talker.pid`, `state/talker.session`, the run-dir pointer `state/talker-cwd`, the reset breadcrumb `state/talker-handoff`, the run's memory stamp `state/talker-memory` and its sessions' last turn events `state/talker-turn` (c-538) |

**What it is allowed to be.** It answers like the user is on a phone, away from the desk
and unable to intervene: brief, concrete, one screen or less, leading with the thing the user can
act on. Pointers, never content: a card id and its stage, a path, a link, never a diff or a
log. It files cards, reads the board, notes on cards and blocks them. It does not read
codebases, debug, design or build in its own context, and that is what keeps it alive
across weeks of conversation. When it catches itself about to investigate, it files a card.

On the user's word Harbor makes a move of a space's flow the user names ("merge c-123 to dev review"):
`kb --actor voice flowmove <id> <move>` ([flows](64-flows.md), c-641).

It holds no credentials of any space (those live in each space's own config dir, which a
house gets and it does not), and it cannot answer a gate: `kb approve` refuses without the
deck's human token. Its rulebook says so, and the token is the mechanism.

**Its deny list.** A fresh config dir has no MCP servers of its own, so the only MCP tools
that reach it are the account-level connectors ever connected on the account, plus the
browser extension. Those are the deny list, along with `Agent(fork)`. A new connector on
the account has to be added there.

**`keel talker start`** stamps the run (`state/talker-started`, which also clears the last
run's fault), records the user's Remote Control consent in the config dir's `.claude.json`
(below), then runs the server as a child with stdin closed, writes its pid to
`state/talker.pid`, relays its output to its own stdout (the log; on Linux through the tmux
pane's `tee`), forwards SIGTERM, SIGINT and SIGHUP (tmux hangs the pane up on a stop) to
the server, and records the session id the first time this run sees one. `url` prints the
phone URL, `status` reports the pid, the health verdict, the recorded session, the URL, the
current run dir, the session's age and rough size, and what `claude agents --json` says.
`stop` sends SIGTERM.

**Its model is pinned** (J-4): the server runs with `ANTHROPIC_MODEL` set to `[models]
converse` (opus), the voice conversation's, in `talker.environment`, so every session it
starts, and a terminal Harbor from `keel talker shell`, runs on it rather than the config
dir's default, whatever the caller's environment held. An environment variable and not
`--model`, because `--model` is a global flag of `claude` (2.1.281) and `remote-control` is
a subcommand whose help cannot be read without a terminal. It takes effect at the next
`keel talker start`; nothing restarts the talker for it.

## The talker's health (c-444)

The talker sat alive and useless for two days (stuck at "Enable Remote Control? (y/n)"),
and then stopped for two more, and nothing said so: `status` exited 0 while the pid lived,
the doctor had no talker line, and the log never showed the prompt. Four mechanisms now:

- **Consent is asserted before launch.** Server mode asks that question when
  `remoteDialogSeen` is not true in the config dir's `.claude.json`, on a stdin nobody
  answers. The old seed copied the key from `~/harbor`'s config, which does not exist on
  the machine it ran on, so it seeded nothing. Since c-610 S1 that seed is `[machine] harbor_dir`'s
  `.claude/.claude.json` (`talker.Paths.seed_source`), and a machine that names no
  `harbor_dir` seeds only the trust entry. `start` now sets `remoteDialogSeen: true` itself (the user
  consented once for this config dir; other keys, `hasUsedRemoteControl` included, are left
  as they are). A `.claude.json` that does not parse is never written over, because it
  still holds the login: `start` writes a fault and exits 2 instead.
- **Every write of that file is atomic** (`keel/claudejson.py`, through
  `keel/atomicfile.py`): a temp file beside it, fsync, `os.replace`, mode 0600. The seed,
  `forget_run`'s pruning and the consent all go through it, because they run while
  `claude` processes (the server, every voice turn) have the same file open, and a
  truncate-then-write is a window in which one of them reads an empty config.
- **The output is read in chunks, not lines** (`keel/talkerwatch.py`). The prompt has no
  newline, so the old line iterator never echoed it and nothing could match it. A trailing
  "(y/n)" (any, not only that one) seen before a session URL writes `state/talker.fault`
  and a `talker: FAULT` line in the log. Nothing is ever typed into it; a URL seen later
  clears the fault.
- **A health verdict scoped to this run.** `talker.health` reads the state files:
  `not-installed` (no unit or plist here; not a problem), `stopped` (installed, not
  running), `fault` (the fault file), `starting` (no session yet, inside the first 60
  seconds), `no-session` (running a minute or more with no session file written since the
  start stamp: a session file or URL left from an earlier run does not count), or
  `serving`. `keel talker status` exits 1 on any fault, and `keel doctor` prints a
  `talker` line and counts every fault as missing.

## The run directory rotates (a fresh conversation on demand)

Remote Control pins one session to a working directory on its own backend and reconnects it
there on every start, so no local file can start a fresh conversation in the same directory.
A reset is therefore a change of directory. `Paths.cwd` is not fixed: it is the current
numbered run dir under `talker/home` (`talker/home/<n>`), recorded in the pointer
file `state/talker-cwd` (`FIRST_RUN` when it is unset). The launchd WorkingDirectory is the
stable base `talker/home`; `start` sets the claude child's cwd to the numbered run dir,
reading the pointer afresh on every start, so a rotation takes effect on the next restart.

**`keel talker fresh`** rotates by hand: it writes a dated breadcrumb to `state/talker-handoff`,
bumps the pointer (`rotate`), re-seeds trust and re-links memory for the new cwd (reusing
`install`'s helpers), prunes numbered run dirs older than the last `KEEP_RUNS` (5, their
transcripts are left in the config dir so history is preserved), restarts the service with
`launchctl kickstart -k` or `systemctl --user restart` (`service.Manager.restart`), and confirms a new session id and the name Harbor. Durable memory
(`memory_src`) is unchanged and re-linked, so the new conversation still knows everything
durable; only the volatile turn history is dropped.

**Auto-reset** does the same from the drain, and it is age-based. Every pass calls
`talker.upkeep`, which rotates the talker when its session is older than
`talker_reset_max_age_seconds` (default 86400, about a day, the way Harbor reset every
morning). It is age-based on purpose: a Remote Control session keeps its turns in its remote
environment, so the local transcript stays 0 bytes and its mtime is the session's CREATION
time, never its last turn (probed 2026-09-17). Neither the context size nor the true idle of
the conversation is visible locally, so a large age is the only honest automatic signal; a
mid-conversation reset at a day old is rare and recoverable (keep talking, or run `keel
talker fresh`). `reset_due` is the predicate and never fires on a session with no transcript.
The one other automatic reason is Harbor's memory moving on main, at a turn boundary its
hooks report ("What a move of main refreshes", below).
Upkeep runs regardless of `drain_paused` (pausing the drain stops new houses, not talker
maintenance), and each auto-reset logs its reason (the session's age). The manual `keel
talker fresh` is the reliable path when the user wants a clean thread now.

## What a move of main refreshes (c-538)

A deploy can teach Harbor something new (to put the user through to Bosun, c-523)
while the voice gateway (`dev.keel.voice`) and the voice conversation, both started
earlier, keep what they started with, so Harbor still says "connecting only works for
cards" until both are reset by hand (r-14). The drain and the deck restart when
HEAD moves; three more pieces notice their own change, each from a STAMP of the paths it
runs on as HEAD has them (`keel/refresh.py`: `git ls-tree HEAD`, so only a committed change
counts and Harbor's own memory writes move nothing), and each at a moment that cuts nothing.
A stamp git cannot give is unknown, and unknown refreshes nothing. The deploy's record says
which of them a deploy set off ([the drain](30-drain.md), "What it refreshes").

- **The voice gateway** (`voice/harbor_voice/codewatch.py`) notes the stamp of `voice/` and
  `bin/keel-voice-gateway` at start (or at the first look that can read one) and looks
  every 30 seconds. Once it moved, it restarts
  when `Gateway.busy` says nothing is going on: no turn in flight, no pin (the voice hold on
  a house or Bosun), no half sentence held, no conversation open, no capture waiting for its
  refine, and no Harbor turn or refine holding the conversation's lock. While one is, it
  waits, logging why once. The restart is a clean stop of the server (a kept-alive Harbor
  process is dropped on the way out) and the service brings it back: systemd's
  `Restart=always`, launchd's `KeepAlive`. The startup log's `code watch:` line says whether
  it is on. A change only to the keel modules the gateway imports does not restart it (the user's
  rule names `voice/`).
- **The voice conversation** carries `memory` in `state/voice-session.json`: the stamp of
  the talker's memory and rulebook it started on
  (`refresh.memory_stamp`: the install's memory repo once it holds the talker's memory,
  c-722, its rulebook included, with the shipped rulebook while the install has none of its
  own and its memory was seeded from the template, the rule `talker.Paths.rules_src` uses,
  c-726 r1.F5; else `<checkout>/talker/memory/` on main; the gateway finds the install from the toml it
  reads, `configpath.install_of`). `open_session` runs
  at the start of every Harbor turn, under the turn lock, and for a SPOKEN turn
  (`open_session(for_memory=True)`, from `send`) `rotation_due` retires the conversation
  when main's stamp differs ("Harbor's memory changed"), with the usual handover line. That
  is a turn boundary by construction, and the dispatcher sends a spoken sentence to Harbor
  only when voice holds no house. A typed ask from the deck or a refine may arrive during a
  hold, so it never retires it for memory; the next spoken turn does. A record from before
  the field takes main's stamp without rotating.
- **The phone talker** records the stamp its run began on (`state/talker-memory`, written by
  `do_fresh` for the new run, or taken from main on first sight). Its config dir has two
  hooks, `UserPromptSubmit` and `Stop`, running `keel talker turn start|over`, which keep each
  session's last event in `state/talker-turn` for this run. Only the server's own process
  sets `KEEL_TALKER_TURNS=1` (`talker.spawn`), so on a voice turn, which shares the config dir,
  the hook exits in the shell and costs nothing, and a `keel talker shell` thread is not
  counted. `talker.upkeep` (the drain, every pass)
  rotates it with `do_fresh` when the stamp moved, every session of the run has said `over`,
  and `drain.voice_holding` finds no live voice hold on a card or on Bosun. No hook heard
  this run means no memory rotation, never a guess; the daily age reset still applies.
  `keel talker status` prints a `memory:` line saying which of these it is waiting on.
  Whether Remote Control's server mode fires these hooks was not probed on the live talker:
  if `state/talker-turn` never appears after a turn, it does not, and only the age reset
  refreshes the phone talker.

## A terminal Harbor over SSH

**`keel talker shell`** opens a terminal Harbor for quick things from an SSH session on a
tailnet device, no browser. A probe on 2026-09-17 (`<install>/history/docs/talker.md`) settled that a terminal
cannot cleanly JOIN the live phone conversation: `claude remote-control -c` from the run dir
refuses ("already being served by another `claude remote-control` instance"), and the server
keeps its turns in the remote environment, so the session's local transcript is empty and
`claude --resume <local uuid>` answers "No conversation found". So `shell` FORKS rather than
joins: it opens a NEW interactive session in the run dir under the talker's config, memory
and rules (same board through `kb`, same memory, separate history), by exec-ing plain
`claude` there. `--print` (or a non-tty stdout) prints the `cd ... && CLAUDE_CONFIG_DIR=...
claude` incantation instead of exec-ing. It is a thin wrapper: no reimplementation.

## What the server-mode probe settled

Run for real on 2026-09-16 against Claude Code 2.1.273, with no terminal and no tmux.
`<install>/history/docs/talker.md` has the raw output.

- **No TTY is needed.** The process ran, connected and stayed up with stdout to a file.
  The `script`-wrapped fallback the plan named is not required. It does repaint its status
  block into the log every few seconds, so the launchd log wants truncating on install.
- **The URL is machine-readable.** `https://claude.ai/code/session_<26 alphanumerics>`,
  wrapped as an OSC 8 hyperlink by default and printed plain with `--capacity 1`. It
  appears three to five seconds after start. `keel/talker.py` matches it on the raw text.
- **`claude agents --json` does not list it.** A remote-control session is a different kind
  from the interactive and background sessions the harness lists. `keel talker status` says
  "no harbor row" rather than claiming a fact it does not have; the talker's own liveness
  is the pid file plus `ps`.
- **The conversation survives a restart three ways**: plain (the environment is preserved
  for the directory and the restart reconnects the same session), `--session-id <id>`, and
  `--continue`. `start` uses the plain form with `--capacity 1`, which reconnects with no id
  to carry and stops the phone spawning a second Harbor in the same directory.
  `--continue` is not used because its roughly four hour window makes an overnight restart
  fail where the plain form does not.
- **The one interactive login is the human's.** Seeding the onboarding flags does not
  substitute for a first run: the OAuth token is looked up per config dir, and only an
  interactive run in that config dir binds it, so the first login is a step the user does by hand.

## The voice gateway

The gateway is a service, not a segment: a microphone, a socket and a speech model are
not static files. It lives in Keel (since 2026-09-17): the package `voice/harbor_voice/` (its Harbor-era name kept, because every script and
the selftest import it by that name), the scripts `bin/keel-voice*`, its own interpreter
`.venv-voice` (Python 3.12: kokoro pins below 3.13, so it can never share `keel/`'s 3.14
stdlib process, and nothing under `keel/` imports it), its state under `state/voice/`,
its log at `state/logs/voice.log`, and the launchd agent `dev.keel.voice` from
`dev.keel.voice.plist` in `etc/`. `<install>/history/docs/voice-two-modes.md` is the plan for what it becomes
(capture and converse); this page is what it is.

**How the phone reaches it.** The gateway binds 127.0.0.1 on `[machine] voice_port` (4390;
`[voice] port` in a file written before c-610 S1, as are `app_url` and `deck_url`, now
`voice_app_url` and `voice_deck_url`: a machine's addresses, not a choice) and
is reached by nothing directly. `keel serve` owns `/voice/...` ([the deck](40-deck.md)):
HTTP is proxied to that port with `X-Forwarded-Host` set to the browser's own Host, any
inbound copy dropped; `/voice/ws` is spliced, a raw socket to the gateway, the request
line and headers forwarded, bytes pumped both ways until either side closes. The
gateway's `ws.same_origin` compares `Origin` against `X-Forwarded-Host`, so that header
is what lets the phone's tailnet origin pass and a foreign page fail (verified through
the tier on 2026-09-17: 101 with a matching Origin, 403 with a foreign one). When
nothing answers on the port the tier answers 503 `voice is down` rather than hanging.
The upgrade is also the deck page's alone (card c-451): it needs the deck's cookie, which the
voice app's own shell hands out, and a same-origin browser, or it is a 403 before anything
reaches the gateway ([the deck](40-deck.md), who may act as the user). The cookie itself is
dropped from what the tier forwards, and the app fetches its own shell before every
reconnect, so a deck restart costs one reconnect.
The page itself, a PWA, is served by the deck at `/segments/voice/app/` from the repo's
`segments/voice/app/` (decision D8: voice keeps its own home-screen app; the two segment
roots are in [segments](70-segments-and-fetch.md)).

**What the page waits on (c-549).** Measured 2026-09-27: its 13 own files, about 150 KB, went
raw and `no-store`, so every open downloaded them again, and at desk width the Talk to rail
read a bare `/api/state` (2 MB raw, 493 KB gzipped) every ten seconds for eight houses. Now
the deck serves a segment app's files other than its shell by its own app file rule
(`serve.get_segment_app` through `reply_app_file`: gzipped when they are text, an ETag,
`no-cache`), so a second open is a 304 per file; the shell stays `no-store`, since it hands
out the cookie. The rail reads `/api/state?scope=deck&part=live` with `If-None-Match`
(`voice.desk.js`), which holds every card with a house: about 46 KB gzipped, and a 304 while
the deck's revision (its fifteen second clock included) has not moved. The phone reads no
state at all. The gateway's own read is the bare document, unchanged.

**The page's shape, and what may sit in it** (rebuilt 2026-09-24, decisions VP-1 to VP-8;
the section "The voice page, a chat you can also talk to" below has the whole of it). Four
body children and a sheet: `.v-top` (the header), `.v-rail` (who you can talk to), `.v-chat`
(the transcript and, at its foot, the dock with the composer and the voice bar) and
`.v-touched` (what the turn touched), with the `.v-sheet` dialog out of flow. On a phone the
body is a flex column and the rail and the touched column are not shown; at
`min-width:900px` it is a three column grid, `280px minmax(0,1fr) 440px`, whose areas are
`top` over `rail chat touched`, and every cell is claimed. There is no tab bar and no drawer
at either width: the page has one section, and the phone's header has a back link to the
deck. Where an older section below says "the orb", it is the voice bar now.

Two rules hold that grid together, and both are there because they were broken (c-310,
2026-09-20, from c-307):

- **Every cell is claimed by exactly one rule, and a cell nothing sits in is `.`.** A named
  area no rule claims is where the grid auto-places a child that has no place of its own.
  Something in the user's browser injected a node at body level, and the old desk stretched it to
  fill a free cell: 420 by 535 of white under the header. It reproduces in no clean
  browser, which is the point. The studio's grid has no free cell at all.
- **The page lays out its own children and nothing else.** A catch-all in
  `segments/voice/app/app.css` takes any body child that is not one of the page's own out
  of flow and down to zero size. It carries no `!important`, deliberately: an inline style
  beats a stylesheet rule, so a browser extension that positions its own widget keeps
  working, and only an unstyled node, which is the pathology, is taken out. The page's
  scripts insert nothing at body level any more: the old warn bar is the dock's reason line.

`tests/test_voice_css.py` is the mechanism behind both. It reads `index.html`, every script
it loads (`tests/voicepage.py`) and `app.css`, and fails when a top-level element has no
place at the desk, when a body-level insertion in the page's scripts is one it does not
know, when a named area is claimed by none or by two, when the catch-all's allowlist and the
`grid-area` rules drift apart, or when `!important` appears in the catch-all. Those are
greps, and the file says so: the render is still the proof, and reproducing it needs a
browser.

**A typed line is a typed turn, answered in text only** (VP-3, the user's decision of
2026-09-24). The page is a chat you can also talk to: a `{"type": "text"}` line goes through
`Gateway.on_typed`, which sets `typed` on the turn, and `Dispatcher._say`, the one place a
turn becomes sound, returns early for it. So a typed turn's filler, narration, streamed parts
(`_house_part` refuses them) and answer are shown and none is spoken, inside a Conversation
too; its end puts the bus back to idle itself (`_rest_typed`), because the speaker's
`finally` that does it for a spoken turn never runs. A typed turn that reaches the give-up
mark is filed as before but NOT hidden from the page, since the promise it breaks is about
audio. The transcript message and the turn both carry `typed`, and the page marks the turn.
The one typed line meant to be heard says `aloud`: the desk's `r`, "say that again".

**A turn names the boards its answer drew** (VP-5). `drawing.read_answer` notes the ids its
pen pushed for the turn (`note_drawn`, in memory, at most `DRAWN_KEEP`), the worker takes
them with the answer (`drawn_for`) into the say record's `boards`, and the dispatcher puts
them on the turn, so `/voice/state` says which board to draw as the receipt.

**A connected house's drawing is read back off the deck** (VP-8). A house draws with `keel
board push --card c-NNN` from its own shell, or with a block `keel converse` cuts out of its
answer, and both write the deck's board store directly: the gateway never holds those ids.
So when a connected turn's answer lands, the worker in `Dispatcher._ask_house` asks
`_house_boards`, which calls `drawing.house_drew`: one loopback `GET /api/boards`
(`deckdigest.fetch_boards`, the same tokenless read as `/api/state`), kept to the rows whose
source card is the connected card, still open, and updated at or after the turn began
(`card_boards_since`, oldest first). The ids go into the same say record's `boards` as
Harbor's. The read runs on its own thread and the turn waits `HOUSE_LIST_TIMEOUT` (2 s) at
most, because a socket timeout alone does not bound a deck that trickles; a deck that fails
or is slow ends the turn with no receipt and one `house-boards-failed` transcript line. A
refusal drew nothing and is not asked about. How a house draws is unchanged.

**One tier, and one instant answer.** The lookup tier is GONE, deleted 2026-09-18
(decision V13, the plan's D4): the router, the argument resolver, the thirteen verbs and
the 436 scored fixtures. It had been off since 2026-09-04 and neither mode needs it, so
the cascade is now `answer -> _ask_harbor` with one exception below. Every other turn in
TALK mode is one headless turn in a persistent voice conversation under the talker's
rules, `claude -p --resume <uuid> --output-format json` with the talker's config dir,
the uuid kept in `state/voice-session.json`. It is its own conversation, not the phone
session: same rulebook, same denies, same memory, separate history. The answer is the
`result` field, delivered into the say inbox by the sending thread, so the filler
corpus, the narrated wait, the barge-in screen and the give-up promise are untouched.
A turn that fails writes its own spoken line into the inbox, once, and the cause into
the log. Its warm board snapshot is built from `kb list --json`, `kb needs-you --json`
and `claude agents --json`.

**The one instant answer: "what's waiting on me".** Code-rendered, no model and no
classifier. `voice/harbor_voice/verbs.py` holds `WAITING`, a table of whole utterances
in `hearing.py`'s style (two of them observed in the user's own transcript, "hey, anything
waiting on me" and "what is waiting on me right now", the rest the same question in the
wordings a person reaches for). It is matched after `hearing.repair`, case-insensitively,
with trailing punctuation ignored and against the WHOLE utterance, so "what's waiting at
the supermarket" can never reach it: that is the difference from the router, which
answered 6 of every 90 ordinary sentences out of the ledger because they carried a
destination word. A match runs `kb needs-you --json` (its own live read, not the warm
snapshot, because the question is about this moment), folds it through the same
`harbor_queue_fold` the deck uses, and renders gate versus notice through `v_queue`. The
counted sentence is led with "On your queue: ", which is what is left of the turn-15 fix
(an answer that does not say which record it read sounds exactly like an answer to a
different question); a sentence that already names the queue is left alone rather than
padded. It
never takes `harbormsg._TURN_LOCK`, so a converse turn in flight neither delays it nor is
delayed by it, and it applies in CONVERSE mode only: capture files everything, including
these words. Provenance is "board, 0.3s" against "Harbor, 14s". Anything that goes wrong,
`kb` refusing, the fold raising, an empty sentence, is a fall to Harbor.

**Its environment is its configuration.** The gateway never parses its config file.
`keel voice install` writes the plist with `KEEL_HOME`, `KEEL_CONFIG` (see "Which config
it reads" below), `KEEL_SEGMENTS_DIR` (from
`segments_dir`, for the one cross-segment read: the cloud-spend TTS spend ledger),
`KEEL_ADAPTERS_DIR` (from `adapters_dir`, for each adapter's `hearing.json`; each pack's is
read from the pack roots too, the install's `packs/` from the `KEEL_CONFIG` it names and the
checkout's, `config.PACK_ROOTS`, c-722),
`KEEL_SERVE_PORT` (from `serve_port`, which is where the digest is read from),
`HARBOR_VOICE_PORT`, `HARBOR_VOICE_SPACE_DEFAULT`, `HARBOR_VOICE_MODE_DEFAULT` and
`HARBOR_VOICE_ENGINE_DEFAULT` (from the `[voice]` table; the last three are the page's
defaults, read by `config.py` and served in `flags.js`), `HARBOR_VOICE_CONVERSE_MODEL`
and `HARBOR_VOICE_REFINE_MODEL` (from the `[models]` table: every turn the gateway runs
names its model, see "The model each turn runs on" below), a PATH with `bin/` and
`~/.local/bin` first (`kb` and `claude`),
`WorkingDirectory` the repo, and both logs to `state/logs/voice.log`. Never
`CLAUDE_CONFIG_DIR`: `harbormsg` sets it per turn, so the gateway's own process holds
none of the talker's rules or credentials. On Linux the unit also carries
`HARBOR_VOICE_STT=sherpa` and `HARBOR_VOICE_TTS=google,kokoro-onnx,browser`
(`LINUX_SPEECH` in `keel/voice.py`; see "Speech on two platforms" below). The plist is a
snapshot: a change to `[voice]` or to `segments_dir` needs `keel voice install --load`
again.

**Which config it reads** (c-711). The gateway, and everything it starts, reads the config
`keel voice install` was run with. When that config is not the checkout's own (an install's
`config.toml`, a sandbox's toml), the service file carries it as `KEEL_CONFIG`, by the one
rule a house's hooks are handed theirs (`config.named_toml`, over `keel/configpath.py`).
When it is the checkout's own `config.toml` or `keel.toml`, nothing is added and `KEEL_HOME`
finds it, as before. Every child inherits the variable, since each is started with the
gateway's own environment plus `KEEL_HOME`:

| What the gateway starts | Where | What it does on that config's board |
|---|---|---|
| `kb list`, `kb needs-you` | `snapshot._kb` | reads, only when the deck does not answer |
| `kb create` as voice | `capture.create` | files a capture, or an answer that could not be spoken |
| `kb repos`, `kb show`, `kb set`, `kb create`, `kb note` as voice | `refineapply.kb` | the refine of one capture, a minute after it is filed |
| `keel board push --talker` | `drawing.push_ops` | draws on a board under that config's `state/boards` |
| `keel converse` | `connected._run` | one turn into a card's house, with the hold |
| Harbor's own `claude` turns | `harbormsg.run_turn`, `harborlive.Process` | whatever `kb` Harbor runs in its turn |

Before c-711 the service file had no `KEEL_CONFIG`, so on an install the gateway was the one
service that did not read the install's config: it and all six rows above loaded
`<checkout>/keel.toml`. The deck, the drain and the backup jobs already named theirs.
The engine's service (`keel/install.py`) and the talker's (`keel/talker.py`) are rendered by
the same rule now.

**A service file is a snapshot, and two acts re-render the gateway's.** A deploy only
restarts the gateway on the file it already has, so c-711 reaches a loaded gateway at the
first of these, whichever comes first:

1. `keel voice install --load`, run with the install's config (the install's `bin/keel`, or
   `KEEL_CONFIG` set).
2. **A save of any voice setting in the deck's Settings.** The deck then re-renders and
   reloads the service by itself (`voice.reload_if_loaded`, from `keel/serve.py`), and the
   deck of an install always runs on the install's config.

The install command says which file the service it wrote will read, one line after
`wrote <file>`: `the service reads <toml>`, and when no config was named, `the service
reads <checkout>/etc/shipyard.example.toml, the checkout's own (no other config was named)`. That second
line is the sign it was run from the checkout's own `bin/keel` with no `KEEL_CONFIG` and
changed nothing; `keel talker install` and `keel install` say the same line
(`configpath.reads_line`). Either way the gateway's first log line then names the file:
`voice: board live via <kb>  config <toml>  state <dir>`. From that start on, the six rows
above write to the install's board.

**What the gateway reads of the talker's follows the config too.** The service file carries
`KEEL_STATE_DIR` (the config's `state_dir`), and the gateway looks for the talker's pid
there (`config.keel_state`, `TALKER_PID_FILE`), which is where `keel talker start` writes it.
One gap in time: between the voice service's re-render (the install command, or a save of a
voice setting) and the talker's own `keel talker install --load`, a talker still running
from an older service file writes its pid under the checkout's state, so the gateway reads
it as not running until the talker is reinstalled.

What `KEEL_CONFIG` does not move: the gateway's OWN writable state. `STATE`, `DATA`, the
voice session file and the talker's folders are still `$KEEL_HOME/state` and `$KEEL_HOME/...`
(`voice/harbor_voice/config.py`), while `keel voice judge`, `keel voice judges` and
`keel voice latency` read `<state_dir>/voice` of the config they are run with. On an install
those are two directories: a `keel voice judge <key> on` there writes a `judges.json` the
gateway does not read. Not fixed by c-711.

**The talker's files move with its config** (c-711). Every file the talker keeps hangs off
its config's `state_dir` (`talker.Paths`): the run-dir pointer `talker-cwd`,
`talker.session`, `talker-handoff`, `talker.pid`, `logs/talker.log`, the start mark
`talker-started`, the fault file `talker.fault`, the stamps `talker-memory` and
`talker-turn`, and its Logins row. Its run dirs (`talker/home/<n>`), its config dir and its
memory stay with the code. So a talker whose service was installed before c-711, and so ran
on `<checkout>/keel.toml`, changes state folder at its next `keel talker install --load`
under an install's config: from `<checkout>/state` to the install's `state_dir`. Nothing
migrates them. Before that one `install --load`, carry the four that hold what a start does
not write again:

```
OLD=<checkout>/state      # where the talker has kept them: the checkout's own state dir
NEW=<install>/state       # the install's state_dir
cp -p "$OLD/talker-cwd" "$OLD/talker.session" "$OLD/talker-handoff" "$OLD/talker-memory" "$NEW/"
keel talker install --load
```

`cp -p` keeps the pointer's time, which is the age clock of the daily reset. A start writes
only the pointer when there is none, the start mark and the pid (`talker.start`); the fault
file is written when a run faults, and `talker-turn` by the next turn's hook. What skipping
the copy costs:

- **No pointer: the server starts in run dir 1 under `talker/home`**, whatever number the old pointer had
  reached (`Paths.run_index`, `FIRST_RUN`). The start is the plain one, which reconnects
  whatever session Remote Control has pinned to that directory (`talker.command`), so an
  old conversation comes back instead of the current one. If run dir 1 was pruned since
  (`prune_runs` keeps five), it is made again empty; whether a session is still pinned to
  that path is Remote Control's to say, not a local file's. Each later `keel talker fresh`
  then walks 2, 3 and on through numbers already used, so "fresh" is not fresh until it
  passes the old number. The age clock starts over.
- **No session file**: `keel talker status` says none recorded until the server prints its
  id, and the next reset's breadcrumb names no old session.
- **No handoff file**: the dated history of resets starts empty.
- **No `talker-memory`**: the stamp of the memory this run started on is gone, and the
  drain's first reading takes main's memory as it is now for it (`talkerturn.run_memory`).
  A memory change committed during the old run then counts as already seen, and the talker
  does not rotate for it until the daily reset. The stamp is read only with the pointer it
  was written for, so it is carried with `talker-cwd` or not at all.

**Which board it will write to, said before it binds.** A house that runs a
scratch gateway from its worktree for a live-socket check, isolated with its own
`KEEL_HOME`, port and PATH, must not have every capture it speaks filed as a real card on
the user's board with nothing in the log to say so. Two things hold that. `KEEL_HOME` defaults to
THIS PACKAGE'S OWN CHECKOUT rather than `~/keel`, so a gateway started from a worktree with no
`KEEL_HOME` keeps its transcript, its filler cache, its recordings (`state/voice/pcm/`) and
its judge log (`judges.jsonl`, and the `judges.json` override beside it) inside that worktree
instead of in the live `state/voice/`. And `serve` prints one line before it builds or binds
anything, `voice: board <live or scratch> via <kb>  config <toml>  state <dir>`, where the word is decided by
the checkout the `kb` it will call belongs to (`config.board_kind`). A gateway whose own code
is a worktree's while that `kb` is the live checkout's refuses to start, and names the two
ways round it: point `KEEL_HOME` at the worktree, or say `KEEL_LIVE_STATE=1` and mean it. The
rule is written here as well as in `keel/config.py` because this package runs from
`.venv-voice` and never imports `keel`; [the start page](00-start-here.md) has the whole of it.

**And a `KEEL_HOME` naming another checkout is not followed.** Defaulting
to the package's own checkout fixed the launches that set no `KEEL_HOME`; a house sets one,
and it names the LIVE checkout, because that is what the drain puts in every house's
environment. So `bin/keel-voice-selftest`, run from a worktree to prove a house's work,
still reached `<live>/bin/kb` and filed its two capture checks as real cards, 84 of them in
a day. `config.borrows_home` now asks the question `keel/config.py` asks: a `KEEL_HOME`
naming a directory that carries a copy of `voice/harbor_voice/config.py` is naming another
checkout's state, and this package keeps its own instead, so `STATE`, `DATA`, `KB`,
`KEEL_TOML`, the recordings and the session file all stay in the checkout the code came
from. `KEEL_LIVE_STATE=1` is the one way through; a `KEEL_HOME` naming a scratch directory
with no package in it is followed as before, which is what every fixture and every scratch
launch relies on. The startup line says when a home was named and not followed, on the same
line as the board, because the value of that line is that it is the first in the log.

**Speech on two platforms** (c-286, 2026-09-19). `speech.make_stt` and `speech.TTSChain`
are the seam between the gateway and the hardware. On macOS the gateway hears through
parakeet-mlx and speaks Google, then torch kokoro, then `say`. On Linux (two ARM cores in
the measurements below) it runs the same model families through ONNX,
`voice/harbor_voice/onnx.py`:

| | macOS | Linux |
|---|---|---|
| Speech in | parakeet-mlx, 0.6B (about 0.45 s) | sherpa-onnx Parakeet TDT CTC 110M int8 (0.067 s for 2 s on two cores, 251 MB) |
| Alternative | | Parakeet TDT 0.6B v2 int8, `HARBOR_VOICE_SHERPA_MODEL=parakeet-0.6b` (0.25 s, 1 GB) |
| Voice chain | google, kokoro, elevenlabs, say, browser | google, kokoro-onnx, browser |
| Selected by | the gateway's defaults (`HARBOR_VOICE_STT=auto`) | the unit: `HARBOR_VOICE_STT=sherpa` |

`auto` probes MLX, then sherpa-onnx, so either platform lands on its own backend. A
backend that will not load is `NoSTT` with the reason on `/voice/health`, never an
exception (under systemd a raise is a restart loop). The model files are not packages:
they live under `HARBOR_VOICE_MODELS` (default `~/voice-bench/models`), the sherpa model
named by an alias or a path, the constructor read off the files (`model.int8.onnx` is CTC,
`encoder.int8.onnx` a transducer). Nothing fetches or verifies them for you: they are put
there by hand, and a gateway that does not find them reports the speech model as missing on
`/voice/health`. `etc/voice-requirements.txt` carries platform markers, so `keel voice venv`
installs the macOS half or the Linux half (sherpa-onnx 1.13.8, kokoro-onnx 0.6.1, numpy;
prebuilt aarch64 wheels, espeak-ng inside kokoro-onnx's own).

**A fallback voice lets go of its memory.** kokoro-onnx is 556 MB on a 12 GB Linux host for a
voice that speaks only when Google fails, so it declares `unload_after`
(`HARBOR_VOICE_TTS_UNLOAD_AFTER`, 600 s). A janitor thread in `TTSChain` drops it after
that long unused, never mid-sentence, and only while an engine ahead of it is up and not
demoted: an engine nothing covers for IS the voice, and is kept. The next failure builds
it again lazily, `browser` covering the gap. Dropping the object is not enough: measured
in a Linux arm64 container, the process sat at 412 MB after the collect and fell to 78 MB
(the import baseline) only after glibc's `malloc_trim(0)`, which `_release_memory` calls.
`/voice/health` shows each such engine's idle age, or when it was unloaded, under
`tts.idle`. Until a Linux host has a Google key (below) kokoro-onnx is its voice, about
5 s a sentence, and is not unloaded.

**The user picks the engine, the gateway picks the speaker, and the chain takes both per call**
(V7, card c-312, 2026-09-20). A control on the voice page beside the mode toggle chooses
which synthesiser speaks: Google or Kokoro. It is remembered in `localStorage`, mirrored
in `?engine=`, sent on every `end` and `text` message beside the mode, and honoured for
that turn; the gateway keeps no copy, the same rule the mode follows. The default is
`[voice] engine_default`, google.

- **One value, two questions.** `speech.Spoken(engine, speaker)` is what a call carries.
  The ENGINE is the user's. The SPEAKER is the gateway's: a ROLE (`harbor` or `house`) rather than
  a voice id. V8 resolved it to a voice per backend through `config.voice_id`; V13 resolves
  it through `config.voice_speaker` first, which answers Harbor for all of them, so the
  role is now carried as a RECORD and the seam is still there for the day a second voice is
  wanted again.
- **There is ONE voice, and a house does not get a second one** (V13, 2026-09-21, and it
  reverses V8, card c-316). Harbor is `en-IN-Chirp3-HD-Charon` on Google and `bm_lewis` on
  the local engines, wherever it happens to be. V8's `Leda`, `af_nova` and `Veena` are gone,
  and so are the three settings behind them. The user's reason, having lived with the second voice
  for a day: a different timbre reads as a different PRODUCT, and the thing the user is talking to
  should stay the thing the user is talking to wherever it goes. What answers "where am I right
  now" is the line instead ("Entering card 272", "Leaving card 272"), which is a fact in
  words and cannot be misheard as somebody else.
- **The floor keeps the persona for free, and the selftest walks the chain to say so.**
  `bin/keel-voice-selftest` fails on any backend in `HARBOR_VOICE_TTS` whose two roles
  resolve to DIFFERENT ids, which is V8's own assertion inverted. `browser` is the one that
  could still have differed, because the gateway sends no samples there and the page speaks
  the words itself: the `speak` message carries `config.voice_speaker`'s answer rather than
  the role, so the page's second-system-voice branch can never fire and the page needed no
  change at all. `elevenlabs` raises unconditionally and has never spoken a word.
- **The tone under the words.** A switch also makes a sound: ONE short note, about 100 ms,
  the same going in and coming back (`speech.tone_pcm`). It was two, rising and falling,
  and a direction is only worth hearing while the two sides sound different; they are not
  different any more, and the line says which way it went. It is arithmetic with no
  synthesiser behind it, so it cannot fail the way a spoken line can, and it goes down the
  same audio channel as speech, which means it works identically on the browser floor where
  the gateway sends no samples at all.
- **The user's word, this machine's backend.** The page says `kokoro` on both platforms and
  `config.resolve_engine` maps it onto whatever the configured chain has: `kokoro` on
  macOS, `kokoro-onnx` on Linux. A word this machine cannot honour resolves to nothing and
  the configured order is used unchanged. `config.engines_for_page` is the list the control
  is offered, so a machine with no local engine in its chain is never offered one, and the
  page hides a control with one value.
- **A choice reorders the chain, it never truncates it.** `TTSChain._order_for` puts the
  chosen engine first and keeps every other one beneath it, `browser` last, so a turn the user
  asked Kokoro for still falls through Google and then to the floor rather than going
  silent. The user's call at the plan gate (2026-09-20): V7's words were about speed and sound,
  not about keeping a turn off the network, so a chosen local engine falls through the
  cloud one like any other. A local-only choice would be one branch there.
- **Every engine takes its voice per call**, so one built object serves every speaker:
  torch kokoro is 787 MB and 11.8 s to construct, and an instance per speaker would put
  that back twice. Demotions stay chain-wide, because a quota stop is a fact about the
  engine and not about the call.
- **Provenance says what actually spoke.** The engine named when a turn starts is a
  prediction; the chain demotes per sentence, so `synthesize` fills `report["engines"]`
  with what produced audio, `Gateway.speak` returns it, `Dispatcher._say` records it on the
  turn as `spokeWith`, and the page appends it to the provenance line ("Harbor, 14s,
  Google, then Kokoro").
- **One set of rendered clips per engine AND per speaker.** The cache key names the engine
  and the voice (`speech.voice_id_for`), and the chain reads it under the CALL's engine, so
  a Charon clip is never played inside a Kokoro turn. `corpus.audio_sets` is the one place
  the pairs are enumerated; `bin/keel-voice-corpus render` fills them (`--engine` and
  `--speaker` each narrow it, with neither it renders all of them) and `keel voice audio`
  counts them, so what is rendered and what is counted cannot disagree. The Google key is
  needed for the google sets alone. SINCE V13 A HOUSE'S SET IS EMPTY, and that is the
  truthful answer rather than an oversight: every fixed line is Harbor's now, and what a
  house says is only ever its ANSWER, which a model writes and which can therefore never be
  a clip. The dimension is kept so the render and the count keep walking ONE enumeration,
  which is what stops a cache reporting itself full while something in it is silent.
- **The control claims nothing about speed.** `config.ENGINE_NOTES` carries one note per
  engine, derived from the platform, and the page's settings sheet reads it. RECORDED FACT
  from the Linux benchmark of 2026-09-18: kokoro-onnx is 4.97 s for 12 words and 14.8 s for
  44 on two Neoverse-N1 cores, with no streaming advantage, so V7's "Kokoro is faster"
  holds on Apple silicon and NOT on Linux, where the note says "about real time".
- **The engine that just spoke is never unloaded.** `_covered` asks whether something ahead
  in the CONFIGURED order is up, which stopped being the whole truth once a choice could
  put a later engine in front: with Kokoro chosen, Google is up and ahead, so the local
  model read as covered and went after ten idle minutes, and the next local turn would open
  on `browser` while 556 MB rebuilt.

**Where the Google key lives, on each platform** (c-299, the user's call on 2026-09-19).
`GoogleTTS._key()` reads exactly one place per platform and nothing else, never an
environment variable and never a guessed path:

| | macOS | Linux |
|---|---|---|
| Where | login keychain, service `harbor-voice-google` | systemd credential `google-tts-key` |
| At rest | the keychain | `~/.config/keel/credentials/google-tts-key`, 0600 in a 0700 dir |
| The gateway reads | `security find-generic-password -w` | `$CREDENTIALS_DIRECTORY/google-tts-key`, the copy the unit's `LoadCredential=` makes at start |
| Put it there | `security add-generic-password -U -s harbor-voice-google -a "$USER" -w` | `keel voice key set` (stdin, never an argument; restarts the gateway) |
| Is it there | `keel voice key check` | `keel voice key check` (set, empty or missing, and the mode; never the value) |

The source sits outside the checkout (no `git add -A` commits it) and outside `state/` (no
backup carries it, the same rule as `human.token`), so a restored machine needs the key set
again with `keel voice key set`. Recorded facts, from an Ubuntu 24.04 container on systemd 255:
`LoadCredential=` works in a user unit (the copy lands in
`/run/user/<uid>/credentials/dev.keel.voice.service/`, 0400); a MISSING source fails the
unit with 243/CREDENTIALS, which `Restart=always` would retry forever, so `keel voice
install` on Linux leaves an empty 0600 source when there is none, and an empty key reads
as no key (Google steps aside on `/voice/health` with the reason). On systemd 255 a user
unit cannot hold an encrypted credential (`systemd-creds --user` is 256), so the key is
plaintext at rest; on 256 the line becomes `SetCredentialEncrypted=` and the gateway does
not change. `harbor_voice.config` pops `CREDENTIALS_DIRECTORY` out of `os.environ` as the
package loads, so no talker turn or `kb` the gateway starts inherits the pointer. That
hides the path, not the permission: a same-user process that knew the unit's name could
still open the directory, the same reach a same-user process has into the macOS keychain.


**The judges' key, and the same rule for every key** (c-313, V10). The classifier the
judges ask (Jev) needs a key of its own, and it lives exactly where the Google key lives on
each platform rather than in a second scheme: `~/.config/keel/credentials/jev-key` on
Linux, the login keychain service `harbor-voice-jev` on macOS. `keel voice key set|check`
took a `--name google|jev` for it (`KEYS` in `keel/voice.py` is the one table of
credential name, keychain service and prompt label), so both keys are the same verb, the
same 0600 file in the same 0700 directory, outside the checkout and outside `state/`, and
`check` still says only whether it is there.

**B0, what a Jev call costs from this machine.** `bin/keel-jev-bench b0 --label <machine>`
is the latency measurement V10's 600 ms budget and every judge's confidence floor rest on.
It is c-295's B0 ported rather than copied (that benchmark's seven-part harness lives elsewhere,
and only B0 was owed here): the same synthetic voice-sized case every call, one
Choice and one Noul, `jev-1.13.0` pinned, 100 calls in `fresh` mode (a new TLS connection
each time, what a hook pays) against 100 in `keep-alive` (one connection reused, what the
long-lived gateway client pays), about a second apart. It writes `runs/B0/<label>.jsonl`
and rebuilds `results/B0.md` from every label present, so each label joins one table; by
default both land in the card directory `KEEL_CARD` names. It refuses to send anything
before `~/.config/jev/retention` declares the route the text goes out under (c-295: the
direct API has no per-request flag, so the declaration is a file the human writes), and
before the key is where it reads it. It imports neither `keel/` nor `harbor_voice/`: the
measurement is of the network and the model, so nothing about the client can move it.
`bin/keel-jev-bench key` answers both questions without a call.

## The judges (V10)

A JUDGE is a named decision point with a typed verdict and two implementations behind the
same call: the RULE, which is what decides today (possibly "always proceed"), and JEV, the
fast classifier reviewed in `state/cards/c-300/review.md`. Built 2026-09-20 (c-313) for
V10 of `<install>/history/docs/voice-next.md`, with every judge shipped in `shadow`, which means it is asked
beside the path that decides, its answer is logged, and the turn goes the way it would have
gone without it. **Nothing here ever turns a judge on.**

Two judges exist, and both are built. `preturn` sits after the transcript exists and before
a Harbor turn is spent (c-324, below); `narrate` is asked per house activity event while a
connected turn narrates itself, and its seat is "The `narrate` seat (V5 beside V10)" below
(c-317).

| Piece | Where |
|---|---|
| The interface, the switch reader, the log writer | `voice/harbor_voice/judges.py` |
| The client: one connection, one budget, the misses | `voice/harbor_voice/jev.py` |
| The switch's other half and the report | `keel/judges.py`, routed from `keel voice judge` and `keel voice judges` |
| The verdict per key, over a window | `keel/judgeverdict.py`, routed from `keel voice judges --since` (c-552) |
| The user's labels, the truth where no outcome says it | `state/voice/judge-labels.json` (c-552) |
| The shipped defaults and the floors | `[voice.judges]` and `[voice.judge_floors]` in the install's `config.toml` |
| The live override, and the log | `state/voice/judges.json`, `state/voice/judges.jsonl` |
| B0, what a call costs from this machine | `bin/keel-jev-bench` |

**The interface, which is a contract and not an implementation detail.** It was settled at
c-313's plan gate and approved as written, because slices 2, 3 and 7 build against it; it
does not change without a note on c-311, c-314 and c-317. A seat writes four things and
nothing else:

```python
rule = judges.rule("preturn", complete=True, addressed=True, route="talk")
ruling = judges.ask("preturn", said, rule, turn=turn.id, criteria={"route": menu})
if ruling["complete"].value is False:
    hold(said)
judges.outcome(turn.id, "carried-on")
```

Four rules make that safe to build against. `ask` ALWAYS returns a `Ruling`: immediately in
`off` and `shadow`, within the budget in `on`, never raising and never blocking past the
budget, so a seat needs no try/except and no timeout of its own. Every answer carries its own
`source`, `rule` or `jev`, and in `off` and `shadow` every source is `rule`, which is what
"on day one Jev decides nothing" is as a mechanism rather than a promise. The switch is per
ANSWER, and a judge AWAITS its call only when at least one of its answers is `on`; otherwise
the call runs on the shadow thread and is never awaited, so shadowing costs the turn nothing.
And a judge asks Jev ONCE per call whatever the number of answers, so `preturn` costs one
round trip for all seven of its answers (three until c-552). `judges.pretend(complete=(False, 0.91))` is the fake judge V10 asks
for: it forces those answers `on` behind a fake client, so the held and quiet paths are
tested with no network anywhere, and `judges.pretend("timeout", ...)` proves a seat fails
open.

**The `preturn` seat, which is the only seat there is** (c-324, 2026-09-20). It is one call
in `Gateway.on_text` (`voice/harbor_voice/server.py`), after the transcript is broadcast and
before the dispatch thread starts: V10's "after the transcript exists and before a Harbor
turn is spent". It is AFTER V1's end-of-utterance detector and never replaces it. Both kinds
of turn go through it, a question and a capture, because `route`'s interesting question is
exactly which of the two this was.

`Gateway._preturn` RETURNS NOTHING, and that is the mechanism rather than a promise: a seat
that hands back no verdict has no branch that can be got wrong, so the turn cannot go
anywhere but where it was going. c-314 (slice 3's state machine) is the card that changes
that signature, when the held partial and the quiet end exist to read a verdict into. The
things that seat will need from here are already done: the ruling is what `judges.ask`
returns, and the turn id below is what an outcome line joins to.

Four decisions inside it, each load-bearing:

- **The rule's verdict is asked of the dispatcher, not written out in the gateway.**
  `Dispatcher.rule_route(said, mode)` returns `capture`, `board_read` or `talk` off the same
  `verbs.is_waiting_question` that `_instant` reads, so the rule logged beside the call is
  the decision the turn is about to make. A rule copied into the gateway could drift, and
  then the log's agreement column would measure the copy instead of the model.
- **The turn id is minted before the turn.** `dispatcher.new_turn_id()` is called in the
  gateway and handed down through `answer`, `capture` and `begin` to `Turn`, which mints its
  own only when nobody passed one. The judge is asked before `Dispatcher.begin` exists to
  mint it, and a CALL line that could not name its turn could never be joined to the OUTCOME
  line that says who was right.
- **Spoken utterances only.** `on_text` is also the typed box's path, and a typed line has no
  transcript: `complete` and `addressed` are trivially true for it, so counting them would
  flatter the very agreement figure the shadow log is kept to produce. The condition is
  `released_at is not None`, which the socket sets for speech and never for typing.
- **No `criteria` override.** `route` is asked with the fixed four-item menu
  `judges.PRETURN` already carries (`talk`, `capture`, `board_read`, `other`), so what leaves
  the machine is the utterance and that menu, and nothing about the user's board. The fuller
  board-read menu belongs with the code-answered reply path, which is c-314's.

The seat is wrapped in a `try`/`except` that logs and moves on. That is not distrust of
`ask`'s contract, which never raises; it is the dispatch path's own rule, the one c-311's
hardening round set for `hear`: what the user just said may never be lost to something that was
only ever asked beside it.

The claim the tests hold is V10's guard itself. `bin/keel-voice-selftest` drives the real
`on_text` against a recording dispatcher with `judges.pretend` answering every way a judge
can (`complete: no`, `addressed: no`, all three routes, all of them at once, and a timeout)
and compares the recorded dispatch argument for argument against the same utterance with
every key `off`. It goes red if the seat ever acts, and it goes red if the rule's route
drifts from the tier the turn takes.

**The switch has two halves, and that is deliberate.** `[voice.judges]` in the install's `config.toml` holds
the shipped defaults, all `shadow`, which is still the one config line for a permanent
change. The live value is `state/voice/judges.json`, written only by `keel voice judge <key>
on|shadow|off`; `default` removes the override. The effective mode is the override if there
is one, else the default, and `keel voice judges`, `/voice/health` and the page's settings
sheet all show the effective value AND where it came from, which is what makes two files read
as one answer.

The reason the live value is not in the config file is mechanical, and it is the user's call of
2026-09-20 amending V10's own wording. The config was then the tracked `keel.toml`, and a tracked file is never
left modified on the main checkout, so a verb rewriting it in place would either leave
`main` dirty or have to make commits on it from a CLI verb. An override file under `state/`
has neither problem, is written by a temp file and a rename, and carries no
secret, so no backup rule changes.

**It fails safe, not convenient.** A key nothing names anywhere reads `off`, never `shadow`:
the fallback must never be the one that starts sending the user's transcripts to a third party. A
key whose mode is `on` but which has no confidence floor reads `shadow` and says so, because
`on` without a floor has no defined meaning. `keel voice judge <key> on` REFUSES to write
that in the first place and names what is missing, which is the mechanism behind V10's "a
judge goes on when the user has read that report and says so": no floor is set until B0's number
from this machine is recorded and a week of the shadow report has been read.

**The one exception to "the gateway never parses its config file".** Its environment is its
configuration, written into the plist or unit by `keel voice install`, and a snapshot cannot
carry a flip that takes effect without a restart. So `voice/harbor_voice/judges.py` reads
`[voice.judges]` and `[voice.judge_floors]` from the toml its `kb` loads (`config.KEEL_TOML`,
which asks `keel/configpath.py`: `KEEL_CONFIG`, else the home's `config.toml`, else its
`keel.toml`, else the shipped example), and nothing else from that file, cached on the mtime and size of both halves, so an ordinary turn costs two
`stat` calls. The reading is deliberately duplicated between `keel/judges.py` and the
gateway's copy, because the two run under different interpreters and neither may import the
other; `voice/harbor_voice/fixtures/judges_switch.json` is read by both suites, so the two
cannot drift silently.

**Fail open, always.** V10's budget is 600 ms per call. A timeout, an HTTP or TLS error, a
dropped connection, a missing key, an undeclared retention route, an answer outside the
question's own criteria, or a second shadow call while one is in flight: each is the rule's
verdict and a counted miss under its own reason, never a stall and never a spoken error. In
`on`, a confidence under the floor is not a miss but a deferral, and the rule decides. One
long-lived `http.client.HTTPSConnection` is held behind a lock and reused; the page
connecting warms it on a thread (`add_client`), because a fresh connection costs about twice
a warm one and a warmer on a timer would hold a connection to a third party while nobody is
there. Shadow calls run on one worker thread with a queue of one, the shape
`HARBOR_TURN_QUEUE_MAX` already has.

**Recorded facts about the wire**, checked against the live API on 2026-09-20 and worth
knowing before touching `jev.py`: a CHOICE answer is `{"type": "choice", "choice": ...,
"confidence": ..., "probabilities": {...}}`, but a NOUL answer is `{"type": "noul", "noul":
0.88}` with NO confidence field at all. The probability is the answer and the certainty at
once, so the value is which side of a half it falls on and the confidence is the distance
from the fence (which is how c-295 scored B3). Reading a `confidence` key for a noul rejects
every noul the API sends. The request id is a header, `x-typesafe-request-id`, and not a body
field.

**The shadow log is the evidence for the flip.** `state/voice/judges.jsonl`, append-only,
three kinds of line. A CALL line carries the turn id, the judge, the mode each answer was
asked under, the input text, the rule's verdict, Jev's verdict and confidence, the latency,
the miss if there was one, and which implementation decided each answer. An OUTCOME line is
written later by the seat (`judges.outcome`) and says what then happened: the user carried on
speaking within two seconds, the user barged in, the turn was abandoned, the user corrected a capture's
label. A FLIP line is written by the verb. Two lines rather than one rewritten line, because
the outcome is known seconds after the call and in `shadow` the call may not even have landed
when the turn ends, and because append-only is what makes it safe for the shadow thread to
write while a turn is running.

`keel voice judges` is that report: the effective switch, then per key the calls, the
agreement with the rule, p50 and p95 latency and the misses by reason, then the disagreements
worth reading (Jev disagreed AND was confident) newest first and capped, each with the
outcome that says who was right, then the last few flips. Agreement is counted only where Jev
actually answered: a miss is an absence rather than a disagreement, and counting it as either
would flatter or damn the model wrongly.

### The shadow week (c-552)

c-542 read a week of the log by hand (`state/cards/c-542/findings.md`) and found three
things wrong with it and four seats worth adding. c-552 fixed the three, added the four,
and made c-542's hand method a command. **No key was turned on and no floor was set.**

**The hygiene.**

- `route` is no longer asked while pinned. The seat ignores it there, and it was wrong 4 of
  6 times, once at 0.98, so asking it only made the numbers worse. `ask(answers=...)` is
  how a seat leaves an answer out (by default a call asks every answer the rule gave a
  verdict for, which is what every seat already passed). An answer not asked is neither
  sent nor logged.
- `addressed` is reworded (`judges.ADDRESSED_QUESTION`). The old wording doubted 12 of 33
  plain questions, never above 0.78. It is still asked on every spoken turn, because a
  push-to-talk turn is addressed by definition, so every one is a free labelled row.
- `keel voice judges` skips call lines whose turn is not in `state/voice/transcript.jsonl`
  and says how many (`judges.on_transcript`). One cause seen: 16 narrate lines a selftest
  wrote into the live log. The count is printed whatever the cause.
- The report prints a disagreement's words only when the line's own facts show a
  personal turn (`judges.shown_personal`: the page not in the work space and no card
  pinned). Otherwise it names the turn and says the words were withheld, because "no work
  turn's words in any output" is the user's rule and this report has no board to place a card.

**The four seats, as answers on the one `preturn` call.** The user's call at the plan gate: three
are asked at the same moment `preturn` is, and the client's one connection sits behind one
lock with a budget that includes the wait for it, so four calls a turn would mostly log as
timeouts. Each ships `shadow`, and each is asked only in the state it is about
(`Gateway._preturn_answers`):

| Key | Asked when | The rule's verdict | Where the truth comes from |
|---|---|---|---|
| `preturn.card` | unpinned, with a personal card to offer | `none`: the talker picks | the talker's `<<keel-connect>>` card, a `connected` outcome |
| `preturn.prefetch` | unpinned talk turns | `none`: the digest only | the first deck read the talker made, a `reads` outcome |
| `preturn.repair` | every spoken turn, after the table | `none`: the table ran | a label |
| `preturn.bargein` | the first utterance after the user cut an answer | `true`: the press cut it | a label |

- **`card`'s menu** is the user's personal cards in the digest the turn already holds, capped at
  40, plus `none`.
- **`prefetch`'s menu** is the deck reads the voice framing names (`judges.READ_SECTIONS`).
  `harborlive.Stream` maps each tool call the talker makes onto one
  (`judges.read_section`) and writes the section names, never the command. A turn that
  fell back to the one-shot path writes no `reads` and counts as unknown.
- **`repair`'s menu** is a closed list of this product's names
  (`judges.REPAIR_VOCABULARY`), so it measures what the exact-string table missed.
- **`bargein`**: the gateway notes a cut in `Gateway.barged_in`, and the next utterance
  spends it whatever it turns out to be.

**The call line carries facts now**: `facts` (the page's space, the pinned card, whether
the listen was hands-free) and `questions` (how many rode the call). Hands-free travels
with its own utterance from the socket's `end`, the way the space does, never through a
gateway-wide field the next listen could overwrite. Those are what let
the verdict place a turn without reading its words, and show whether the wider call got
slower.

**The verdict** (`keel voice judges --since YYYY-MM-DD [--days 7] [--labels PATH]`).

- **Rows.** Call lines on a real turn inside the window, and only personal ones. c-542's
  exclude rule, made mechanical:
  - a label's `space` decides first;
  - then the card the turn touches (a pinned card, or the card a talker connected to), by
    its space on the board;
  - with no card, the row counts when its page was not in the work space and its session
    (turns under 15 minutes apart) touched no work card and matched no adapter's
    `hearing.json` words.
  - A line from before c-552 has no facts, so it counts only by a label.
- **Truth.** A label first. Then an outcome: `connected` or any other outcome for `card`,
  `reads` for `prefetch`, `carried-on` or `abandoned` for `complete`, and a push-to-talk
  listen for `addressed`. Agreement with the rule is never taken for truth.
- **Numbers.** Per key: turns, personal rows, the rule's rate on the rows with a known
  truth, and the 95% Wilson interval of Jev on its calls at 0.9 or more. Then p50, p95 and
  over-600 ms on every call that carried the key, with the questions a call.
- **The bar.**
  - Flip on: 30 or more personal turns with a known truth, and the lower bound above the
    rule's rate.
  - Drop: the same 30 and a log that rules against Jev (never confident, or the upper
    bound below the rule's rate).
  - Needs more data: everything else.
- **Labelling.** It lists the turn ids still worth labelling, ids only. **It never prints
  what was said**, in either space.

The labels file is `state/voice/judge-labels.json`, a turn id to `{space, <answer>: value}`,
`null` where a turn cannot be read. `state/cards/c-552/judge-labels.seed.json` is c-542's
38 personal readings in that form. Run over c-542's week with it, the verdict reproduces
c-542's published numbers: `complete` needs more data (31 of 33, 3 confident, lower 0.44),
`addressed` drop, and `route` needs more data.

**Seats c-300 named that were not built, and c-542's verdict on each.** Recorded here so
nobody re-derives them:

| Seat | c-542's verdict |
|---|---|
| interruption-worthiness for unprompted speech | build as a shadow test, low priority |
| composer prefill | build as a shadow test once c-303's corrections log has 30 corrections |
| new board or continue (board seat 2) | build as a shadow test, log only, low priority |
| leave beside connect (board seat 4) | drop: `verbs.leave_intent` caught both real leaves |
| icon choice (board seat 1) | drop: a Claude already picks the icon |
| draw or not (board seat 3) | drop: a Claude is already generating the answer |

**Both verbs always run here.** The switch and the log live in `state/voice/` beside the
gateway that reads them, so `keel voice judge` and `keel voice judges` read and write this
machine's files directly.

**What leaves the machine, and what does not.** The utterance text and the criteria of the
questions asked, under the retention route `~/.config/jev/retention` declares, which the user
accepted for both spaces on 2026-09-19. Audio never goes. No card titles and no board
contents go: `route`'s criteria are the fixed menu of about five board reads from c-300, and
a caller that passes its own `criteria` owns what is in them. Since c-552 one caller does
put titles in: the `card` answer's menu is the ids and titles of the user's PERSONAL cards in the
digest, unpinned only, and never a work card's. The client refuses to send a
byte before that file declares something true, so the route is a fact on the machine rather
than a memory.

**`keel doctor` says whether the judges can reach the key**, on its own `judges` line, with
the modes and the call and miss counts beside it. The answer comes from the GATEWAY through
`/voice/health`, because only that process knows whether the unit's `LoadCredential=` actually
delivered the copy it reads; with nothing answering on the port, doctor checks the source file
instead and says that is what it did, so a gateway that is down is never reported as a missing
key.


**Mishearings, and where the employer's live.** `hearing.repair` gained the sherpa Parakeet model's
(observed 2026-09-19 through both Parakeets over synthetic voices): Kiel, Kel and Kil as
Keel, Harba and Harbard as Harbor, "the cbe" as the queue. An employer's name may only
be written in its pack (`<install>/packs/work/`, [packs](62-packs.md)), so each adapter can carry a `hearing.json` of its own
(`<pack>/hearing.json`), each entry naming what was said and where it was heard;
`hearing` merges them at import, from the adapters tree and every pack root (an install's
own pack is in the install, not the checkout: `config.PACK_ROOTS`, c-722 landing B; `keel
voice judges` reads the same words through `judgeverdict.vocabulary` and `packs.roots`), its own entries win a clash, and a malformed table is
skipped and named in `ADAPTER_ERRORS`.

**Which gateway the phone reaches.** The `/voice/` tier proxies to the gateway on its own
host's loopback, and there is no setting that points a deck's tier anywhere else, because
voice and its board are one host by construction (the digest's 127.0.0.1 read,
`harbor_voice.config.SERVE_PORT`).

**The verbs.** `keel voice venv` builds `.venv-voice` from `etc/voice-requirements.txt`
on the newest versioned python3 at or below `MAX_PY` (3.12; a bare `python3` is never
chosen, and a venv outside the 3.10 to 3.12 range is rebuilt rather than reused). The
file carries platform markers: macOS installs parakeet-mlx and kokoro, Linux sherpa-onnx
and kokoro-onnx, so the same verb builds either.
`keel voice install [--load]` writes `dev.keel.voice.plist` in the install's `services/` (c-722, `Config.services_dir`) (on Linux
`dev.keel.voice.service`, with `CPUWeight=400` so a spoken turn outranks the houses in the
engine's unit), and with `--load` hands it to `keel/service.py`, which on macOS copies it
to `~/Library/LaunchAgents/`, bootstraps it and kickstarts it (a bootstrap alone is not
always a start, c-747, [install](88-install.md)), booting out a loaded copy first
and WAITING for that bootout to finish (`launchctl bootout` returns before launchd has
let go, and bootstrapping while it still holds the label fails with "Bootstrap failed: 5:
Input/output error", which leaves the gateway down behind a message that reads like an
ordinary error). `keel voice uninstall` stops it and removes that copy. `keel voice key set|check` is the
Google key on Linux (above). `keel voice audio` counts the rendered filler, ack and handoff clips
(`N/M lines have audio`, exit 1 while any is missing), one set per engine the voice control
offers and per speaker inside it, a line each (`google as harbor: 364/364`,
`google as house: 0/1, 1 missing`), and `--render` renders the missing
ones through `bin/keel-voice-corpus render` in the gateway's own environment, so each clip
is keyed to the voice the gateway will ask for; on Linux it refuses without the Google key
when a GOOGLE set is short, and renders the local sets without one. `keel voice status`
prints loaded or not, the pid, the health line (the speech and voice backends, and
that the lookup tier is removed), the venv,
the data and log paths, and the process command line; exit 1 when nothing answers.
`/voice/health` no longer carries a `router` block: it reports `"lookupTier": "removed"`
instead, said out loud rather than by omission, because a key that simply vanished would
read to the page's sheet, the deck's Voice card and `keel voice status` as a gateway too
old to answer. `keel doctor`
reads the same probe and counts a silent gateway as missing.

**Runtime files.** `state/voice/`: the `say/`, `progress/` and `opening/` inboxes,
`transcript.jsonl`, `tts-usage.json`, the bus mirror files, and `cache/filler-audio/`,
the filler lines, the capture acks and the fixed handoff lines rendered once by
`bin/keel-voice-corpus render` (regenerable, so a cache). One clip per line per
(engine, speaker), which is what the file name hashes: the text and the voice, and the
voice names the engine and the role. `state/voice-session.json`: the voice conversation's record, `{uuid, turns,
started_at, memory}`. `state/logs/voice.log`.

**Tests.** `tests/test_serve.py` proves the tier against a fake gateway (the forwarded
host, the relayed answer, the 503 without a hang, the splice carrying bytes both ways);
`tests/test_voice.py` the plist and its environment, the interpreter search and the
status lines; `tests/test_voice_css.py` the page's desk layout (above); `tests/test_deck_cli.py` the fold, the digest's caps and counts, the tables
and the `keel deck` verb with the loopback read patched. `make test-all` (on demand, and at every deploy, which requires it to pass), and `make test` when the change reaches it (`tests/selector.py`: `voice/`, what the voice package or the selftest imports, the voice and cloud-spend segments, a pack's `hearing.json`), then run `bin/keel-voice-selftest` from `.venv-voice` (about
a minute, offline, with a stub `claude` and `kb`) when the venv exists, and prints a
skip note when it does not. The stdlib suite never imports the package.

**A check about "the same pass" holds the pass, rather than hoping for it** (c-418).
`Dispatcher.pass_gate` is a lock held for the whole of each pass of the watch loop, which
claims the say inbox and then the opener inbox. The check that an opener losing the race to
the answer is never spoken used to write the two files back to back and rely on no pass
running between them, which a loaded machine broke. It now writes both while holding the
gate, with a sleep longer than a pass between them to prove it. In production the lock is
never contended.

**The selftest runs behind a fence of its own** (2026-09-20), for the reason `tests/fence.py`
exists for the stdlib suite. Its capture checks speak "a thought" and "remember the bearing
export" and what they prove is that a card comes back, and a house runs the file many times
per card with `KEEL_HOME` naming the live checkout: 84 real cards in a day, 69 of them from
one card's runs in a single 43 minutes, and nothing in the output said which board it had.
Two sections built a throwaway `KEEL_HOME` with a stub `kb` of their own; the two that file
through the real dispatcher had none.

So the run owns a scratch world, built before `harbor_voice` is imported, because that is
where the package reads every path it will use. Every `KEEL_*` and `HARBOR_VOICE_*` the
caller had is dropped; `HOME`, `XDG_CONFIG_HOME` and `TMPDIR` move inside the scratch (`~` is
half the trap, since a config may say `state_dir = "~/<install>/state"`); a recording `kb`
stand-in sits both first on `PATH` and at the path `config.KB` resolves to, and answers the
way `kb` does; `KEEL_CONFIG` names a scratch toml, and
`KEEL_SERVE_PORT` a closed port, so neither the file nor the HTTP route reaches a real board.
`KEEL_SEGMENTS_DIR` and `KEEL_ADAPTERS_DIR` are this checkout's own, because the one
cross-segment read (`speech._cloud_spend_record`) and the hearing merge have to be the real
files, and `HF_HOME` is the machine's model cache with `HF_HUB_OFFLINE=1` beside it, so
moving `HOME` cannot turn a cached read of potion-base-8M into a download on a merge gate.

`fence_section()` runs last and is what fails the run when a new section forgets: the `kb`
the package would call is inside the scratch, the two captures that leaked still file and
filed there, every writable path the package decided is inside the scratch, the environment
still is, no board is reachable over HTTP, no live board holds the run's mark (below), and
the real `state/voice` trees (this checkout's and the live checkout's) and the `data/` tree
under `<install>/segments/cloud-spend` have the fingerprints they had at the start.

**The board is checked by the run's mark, not by its mtime** (c-417, 2026-09-23). The
witness used to fingerprint `board.db` by mtime and size and `state/cards` and `state/logs`
by their name lists, and all three change on a machine where Keel is running for reasons
that are not the run: a WAL checkpoint by the drain, a hook or the hourly backup, a card
filed by anything, a house starting. So the selftest failed on other people's
activity. The run now picks a nonce (`RUN_NONCE`), hands it to the package as
`HARBOR_VOICE_RUN_NONCE`, and every `kb create` the package makes carries it as
`--option run_nonce=<it>` (`snapshot._kb`; the gateway never sets it). At the end the
fence asserts that every create the stand-in recorded carries the mark, that the reader
finds it on a planted scratch board, and that neither live board, opened read-only, holds a
card or an event with it. The HTTP check above already proves the live board is not reachable from the run; the
local file is asked anyway. A REAL TREE'S FINGERPRINT IS ITS NAME LIST AND NOTHING ELSE, minus
dot entries, because two things write into the live tree on their own clock while any run
of this is going on and neither of them is the run (c-316): the gateway mirrors its state
by writing `._X` and renaming it over `X` twice a second, which bumps the directory's mtime
and makes the `._` names flicker, and the drain appends to `drain.log` every half minute.
Asking whether a shared directory CHANGED cannot answer "did this run write here" on a
machine where Keel is running; asking whether anything appeared or vanished can, and a
stray write creates something. The case a name list cannot see, a section appending to a
live log, is covered earlier and better by the writable-paths check above it. `bin/keel-voice-selftest --fence-report` runs the prologue alone, files one capture
through it and prints what it decided as JSON; `tests/test_live_state.py` runs that under a
house's environment against a fake live checkout, which is the whole leak in one test and
needs no `.venv-voice`.

## Two modes: capture and talk

One gateway, one socket, one page, two paths after the speech model, built 2026-09-17 to
`<install>/history/docs/voice-two-modes.md` sections 1 to 3. The split is by what the user wants back: a
conversation (a spoken answer, the model in the loop) or a receipt (a card on the board,
no model anywhere).

**The mode is the message's, never the server's.** Each `end` and `text` carries `mode`
("capture" or "talk"; absent means talk, which is what every client written before the
modes meant), for a capture `space`, and since V7 `engine` (google or kokoro; absent means
the configured chain). There is no mode, space or engine state in the process, so there is
nothing for the page to drift from.

**Capture has no model in it and no wait.** `on_utterance` runs the speech model and the
vocabulary repair as always, then `Dispatcher.capture` files the words through
`voice/harbor_voice/capture.py`: one `kb --actor voice create`, inbox, topic `voice`,
title the first sentence clipped to `CAPTURE_TITLE_CHARS`, brief the user's whole sentence as a
quote and nothing under it, `source=voice`, `capture=raw`, and `heard=<json>` when the
repair table changed a word. A leading "work:" or "personal:" files it there and stays in
the quote. The actor is `voice` because `--actor human` needs the deck's token and this
process must never hold one; the stage is inbox with no exception, so a capture can never
assign, stage or start anything. Then a fixed ack is played from the same rendered cache
as the filler (`corpus.ACKS`, `bin/keel-voice-corpus render`), so speaking it costs no
synthesiser call: release to ack is under a second. The ramble is never read back and the
card id is never spoken, it is drawn under the turn from the `captured` broadcast.
`corpus.ACK_FAILED` is the one failure line, and the user's words are still on the page and in
the transcript when it plays.

**The page carries the mode.** A sticky two-position segmented control (Capture and Talk)
sits in the gap between the transcript and the orb, 52px tall so that each half clears the
44px tap target (it was 44 overall and 36 a half, which is under the budget in the one
control this app is used through), remembered in `localStorage` and mirrored in `?mode=`; the orb's label reads "Hold to capture" or "Hold
to talk" so the mode is readable without looking at the control. The header's title is
the space, Personal or Work, with the deck's own swap glyph beside it. The manifest has a
second shortcut, "Capture" (`?listen=once&mode=capture`), so a lock-screen route opens
straight into a hands-free capture. There is still no tab bar: the app has one section
and the toggle is a mode of it, not a destination. **Since VP-2 (2026-09-24) there is no
toggle**: the page rests in talk, and a capture is one hold armed from the composer's +
menu as "Capture next" (or by the shortcut's `?mode=capture`, for that launch only), spent
by the take; `modeDefault` in flags.js is no longer read by the page.

**Talk is the same Harbor turn, with four things added.** The turn now carries a DECK
digest (`index.as_json` of the warm snapshot, which is the deck's own state document
reduced) and the sentence that says to answer from it and not to run `kb list`, which
removes the two `kb` reads that were the first two tool calls of every turn. It carries
the command contract, so a command is done and then reported in one sentence with the
card id. It carries the egress split (below), so a turn does not have to recall a memory
file to know what it may say out loud. It runs under `harbormsg.conversation_turn`
(`_TURN_LOCK` in this process and an `flock` on `state/voice/harbor-turn.lock` across
processes, so a question typed on one of Harbor's boards, which runs as its own
`keel-voice ask --wait` process, cannot race it: [the board](45-board.md), "The ask box"),
so a second utterance waits rather than racing the first on the same conversation, and a
third, with `HARBOR_TURN_QUEUE_MAX` at 1, is answered with the fixed line "One at a time,
I'm still on the last one" rather than queued. Capture never takes that lock. And an
answer the user could not hear (the give-up promise, or presence saying the user is not there) is
filed as a personal inbox card with `kind=answer` through `harbormsg.queue_answer`
(decision D3), because the board is the one place the user looks; the give-up path still
redacts the text from the voice page, the not-live path does not, because nobody was
promised anything there. `_finish_silent` marks the turn `done` BEFORE it files the card
(a transcript line sits between them), so `phase` is not the signal that the answer was
filed: on the give-up path `turn_over` is, which fires after it. The selftest waits on
that (c-545, r-22).

**The conversation is bounded and rotates.** `state/voice-session.json` holds
`{uuid, turns, started_at, memory}` (the bare uuid in `state/voice-session` is migrated once and
removed). At `VOICE_SESSION_MAX_TURNS` (40) or `VOICE_SESSION_MAX_AGE` (86400) the
conversation is retired, and so it is when Harbor's memory moved on main since it started
(c-538, "What a move of main refreshes", above): a fresh uuid, `--session-id` rather than
`--resume`, and the first turn's framing carries a one line handover naming the last three things the user said,
from the transcript. Every `-p --resume` re-reads the whole transcript, so this is the
one latency cost that otherwise grows silently. The lost-conversation repair is
unchanged. The talker's own memory says the same thing from its side:
`<install>/memory/talker/voice-turn-shape.md` replaced `voice-answer-headline-first`, whose
`opening` and `say` channels were the pane era's and whose shape truncated its own
answer.

**The model each turn runs on.** Every `claude -p` the gateway runs names `--model`
(`harbormsg.turn_command`), because a turn with none runs on the account's own default,
which is what a house did for five days before the overnight clearance (c-434). The voice
conversation runs on `config.CONVERSE_MODEL` (opus) and the refine asks for
`config.REFINE_MODEL` (sonnet); since D-3 the refine runs in a session of its own, so the
two never share a transcript. Both come from `[models]` in the install's `config.toml` through the service file, and the
package holds the same two values for a service file written before the keys existed. The
talker runs on `converse` too, through `ANTHROPIC_MODEL` (J-4, "The talker" above).
A board's ask box reaches a card's own house on that card's model, and Harbor through this
conversation, so it needs no pin of its own.

**The refine is the second half of a capture.** `voice/harbor_voice/refine.py` holds an
in-memory FIFO that a capture's own hook feeds, and a thread drains it once the user has been
quiet for `REFINE_DELAY_SECONDS` (20), so a run of captures is refined after the run
rather than during it. Each card gets ONE turn, IN A SESSION OF ITS OWN (D-3, c-438): a
fresh `claude -p --session-id <new uuid>`, never `--resume` of Harbor's voice
conversation, and not persisted, so a capture no longer grows the transcript Harbor
re-reads every turn or counts toward its 40-turn rotation. It still takes the conversation
lock (`harbormsg.acquire_turn`, C-8), without blocking, and puts it straight back down if
a converse turn has arrived: two `claude` turns at once on two cores would delay
the answer the user is listening for. `REFINE_ENABLED` turns the whole of it off, and
`/voice/health` reports the queue.

**The refine has no tools; Keel makes its writes** (lane D review round 2, D-10 to D-12).
A capture's words are the user's, verbatim, so "block c-312" said into the microphone must stay
words. The turn runs with `--tools ""` (the empty value last, after the prompt, because a
variadic flag before it would swallow it), `--strict-mcp-config`,
`--disable-slash-commands` and `--no-session-persistence`, plus `--output-format json
--json-schema <schema>` built per call by `refineapply.schema` (the exact keys,
`additionalProperties: false`, the caps, and the real repo keys and topics as enums;
round 3), and answers with ONE JSON object, read from the envelope's `structured_output`
and nowhere else (Claude Code 2.1.281, `tests/fixtures/harness/README.md`); a turn with
no structured output changes nothing, because a real no-tools turn without the schema wrote
prose and a pretend tool call before its JSON. The object: `title`, `topic`, `repo`, `note`, `question`, `choices`, `split`, `line`.
`voice/harbor_voice/refineapply.py` parses it strictly (exactly those keys, capped
lengths, `repo` one of the keys Keel read with `kb repos` for that space, `topic` one of the
board's own topics) and then writes it onto THE captured card only, through `kb` as
`voice`: the title; `repo` and `topic` always with `--assumed`, and never a field whose
provenance is `stated` (it reads the card first); the note; a split as inbox cards `--from`
the card with no parent (never assigned, V11), each noted on the original; a question as
`kb block` with `options.choices`; and `options.capture=refined`. A malformed answer is
logged and changes nothing. D6's automatic re-create in work is gone from the refine: a work
suggestion goes in its note and the move is the user's. **It never speaks**: `Refiner` is handed no
`say` and no presence, and its `line` goes to `state/logs/voice.log`.

**`KEEL_REFINE_CARD`, the second belt.** Every `kb` call `refineapply` makes carries it,
and `kb` (`keel/refinescope.py`, checked in `cli.main` before either door) then lets reads
through, lets `set`, `note` and `block` through on that card only and never a `set` of
`parent`, `after` or `from`, lets `create` through only `--from` that card with no
`--parent` or `--after`, refuses every other verb on any card (`split`, `unblock`,
`stage`, `approve`, `claim` and the rest), and writes as `voice`. Set and empty is a scope
with nothing in it and refuses every verb. `kb set --assumed` and `kb create --assumed` are
taken only from `voice`, which never overwrites a `stated` tracked field either
(`Board._check_assumed`, `Board._check_stated`), and `--assumed` travels through the deck's actions
(`actions.create_argv` and `actions.set_argv`).

**A card that changes code needs a repo, and a capture never asks for it out loud** (D-3,
c-438). A card with no `repo` is an
errand: no worktree, no checkout, so it cannot change a line (see [cards and
gates](10-cards-and-gates.md)). A code fix filed with no
repo cannot be built (c-296). The converse turn's `FRAMING` still
asks the user which when the user's words do not settle it, because the user is in that conversation. The
refine does not: it names the likeliest key and Keel files it as `assumed`, so the user's own
later change is the correction. A question only the user can answer blocks the card with the
question as the reason and the choices in `options.choices`, and a blocked card is on the
deck's Attention view (Q8). The CAPTURE itself is deliberately left out of all this: it is
one `kb create` with no model in it and it stays under a second. The talker has the
converse rule from its side, in `<install>/memory/talker/cards-from-conversation.md`.

**What the page is told.** `/voice/flags.js` gains `modeDefault` and `captureDefaultSpace`
from `config.py`, which reads `HARBOR_VOICE_MODE_DEFAULT` and
`HARBOR_VOICE_SPACE_DEFAULT` from the environment `keel voice install` writes, whose
values are `[voice] mode_default` and `space_default` in the install's `config.toml`. One source, two
readers. V7 added a third the same way: `engineDefault` from
`HARBOR_VOICE_ENGINE_DEFAULT` and `[voice] engine_default`, beside `engines`, the list of
synthesisers this machine's chain can actually honour (see "The user picks the engine" above).

## End of utterance, and the corpus that tunes it

Built 2026-09-20 (card c-311, requirement V1 in `<install>/history/docs/voice-next.md`). Before it, the
gateway had no end-of-utterance detection at all: push to talk ended on the release, and
hands-free (`?listen=1`) had no release, so the page armed a 20 second backstop and every
hands-free turn waited the whole of it. That was the whole of the slowness.

**The detector is a timing signal and nothing else.** `voice/harbor_voice/vad.py` holds
two classes and the seam between them is the design. `Endpointer` is a hangover timer over
`(is_speech, seconds)` with no audio in it at all, pure standard library, tested by
`make test`. `SileroVAD` is sherpa-onnx's `VoiceActivityDetector` used only as a per-frame
speech-or-silence classifier: it never pops a segment, so the bytes handed to
`stt.transcribe` are byte for byte what they were before. `make_vad` mirrors
`speech.make_stt`: `auto` looks, `off` refuses, and a missing wheel or model gives a
`NullVAD` that never fires, which is exactly today's behaviour.

**It is armed only on a hands-free listen.** `{"type":"start"}` carries `handsFree`, true
when the page auto-armed the listen rather than a finger doing it. A finger on the orb is
an explicit statement that the user is still talking, so push to talk is untouched.

**`end` is still the only flush.** The gateway sends `{"type":"endpoint","generation":n}`
and the PAGE answers with the ordinary `{"type":"end"}`, the same one a release sends. The
mode and the space still ride on it, read at the moment the turn ends, and a page that
does not know the message waits out its own backstop. If the detector never fires, nothing
about a turn changes.

**The detector never hears the gateway.** Three layers: the browser's own
`echoCancellation: true`, then `Gateway.hear` feeding the detector only while `bus.state`
is not `speaking`, then a RESET rather than a pause whenever it is. After the gateway
stops talking, fresh speech has to arrive before any hangover can run, so no part of a
hangover can be built out of the gateway's own voice. `bus.state` is an in-process
attribute because this is asked once per audio frame.

**The hangover shipped on day one is 2.5 s, which is not the tuned number.** V1 targets
700 ms. 2.5 s is 3.5x that, chosen from the safe side so no plausible measurement could
move it up, and it replaces a 20 second backstop with about 3 seconds from the day it
merged. `[voice] vad = "off"` in the install's `config.toml` plus `keel voice install` is the one line
back.

**It is 2.0 s since 2026-09-24, and a key** (lane H, H6). Measured on the Linux host's corpus, the
two-stage rule below cut the user mid-sentence 11 times in 32 and a plain 2.0 s hangover 2 in
27; the user approved 2.0 s, and the two-stage rule stays scored and unused. The value is
`[voice] vad_hangover` in the install's `config.toml` (`Config.voice_vad_hangover`), carried into the
gateway's environment as `HARBOR_VOICE_VAD_HANGOVER` by `keel voice install` the way every
other `[voice]` key travels (V4), so changing it is a config change plus `keel voice install
--load`, never a code change; `harbor_voice.config.VAD_HANGOVER` defaults to 2.0 too, for a
unit written before the key. `keel voice status` prints the gateway's running value beside
the configured one ("as configured", or the configured value and the command that applies
it), and prints the configured one when nothing answers; `keel doctor` does the same on its
voice line whenever the gateway reports a detector.

**The corpus, and it is meant to be turned off again.** There was nothing to measure a
hangover against: `state/voice/transcript.jsonl` holds text, and the utterance's PCM was
dropped straight after transcription. So `voice/harbor_voice/record.py` writes each
utterance to `state/voice/pcm/<id>.wav` under `[voice] record` and the transcript line
carries a `pcm` pointer (`Turn.pcm`). It is the user's voice, so five guards: the directory is
0700 and every wav 0600, set explicitly at creation rather than left to the umask and
repaired on anything already there; never backed up (`bin/keel-backup` prunes
`state/voice/pcm` the way it prunes the TTS cache); capped at `HARBOR_VOICE_RECORD_MAX_MB`;
expired after `HARBOR_VOICE_RECORD_KEEP_DAYS`; and shown on `/voice/health` and by
`keel voice status`, with `keel voice corpus --delete` to remove it. `keel doctor` says so
once it has been recording more than four days. It is off unless the user turns it on: the
schema's default and, since c-722, the shipped example's `record = false`, so a new install
records nothing; an install that set it keeps its own.

The modes are worth naming because the first cut of the recorder set none, so under a
022 umask the user's voice landed at 0644 in a 0755 directory, on a machine that also runs
a web server. Review caught it before it shipped (2026-09-20). The mode is set by `os.open`
at creation, never chmodded afterwards, because afterwards leaves a window in which the
file exists and is readable.

**Measuring it.** `bin/keel-voice-vad-measure` sweeps candidate hangovers over the corpus
and prints, per mode, the seconds each would have saved and how often it would have cut
mid-sentence (defined as a fire with more speech after it, which needs no labelling). It
runs the gateway's own `Endpointer`, so the measurement and the live path cannot drift.
`--gaps` reads the transcript for the cuts the shipped hangover itself took wrongly, which
show as two turns seconds apart. It counts a TURN once, by its id (2026-09-24, lane H): a
capture writes `captured` and then `answer`, both carrying the user's words, so before that every
capture read as a cut that fired early, "0.0s" with the same sentence on both sides, seven
of them (`tests/test_voice_stages.py`).

**The two-stage rule, scored and not switched on** (D-6, c-323, 2026-09-23). `--two-stage`
replays a second rule over the same corpus: at a short pause (`vad.TWO_STAGE_SHORT`, 0.7 s)
the audio so far is transcribed with this machine's speech model, and the turn ends there
when `vad.looks_complete` says the words look finished (not ending on a comma, a
conjunction, an article or a filler, `vad.OPEN_ENDINGS`); otherwise it waits for the long
pause (`TWO_STAGE_LONG`, 2 s). It prints the same columns as the sweep, beside the single
0.7 s and 2 s hangovers, plus how many recordings ended at the short pause.
`vad.two_stage_fire_at` is the rule and nothing live calls it: the gateway ends a
hands-free utterance with `Endpointer` at `VAD_HANGOVER`, and on these numbers (11 cuts in
32 against 2 in 27 for a plain 2.0 s) it was decided to stay that way (H6, above). The numbers come from a Linux host's corpus (macOS has no detector model there), and the corpus is kept until they have been read (tests:
`tests/test_voice.py` `TwoStageRuleTest`).

**The model.** `silero_vad.onnx`, 629 KB, from sherpa-onnx's own `asr-models` release. It
lives in `HARBOR_VOICE_MODELS` (`~/voice-bench/models`) beside the Parakeet models, put there
by hand: nothing fetches it or checks its sum, and a gateway that does not find it keeps the
20 second backstop (`make_vad` degrades to a detector that never fires). Measured on a Linux
host on 2026-09-20: it loads in 28 ms and runs one 32 ms frame in 0.248 ms on a single core,
130x realtime.

**One code path on both platforms.** `etc/voice-requirements.txt` names `sherpa-onnx` for
macOS as well as Linux, so `auto` finds a detector on either, but the model file is only
where somebody put it. The macOS wheel was landed without being resolved from Linux, so
whether it fights parakeet-mlx's tree is answered at the next `keel voice venv` there. If it
does, the line comes out and that machine keeps the 20 second backstop.

## The conversation, pause and resume, and the three paths a verdict reaches

Built 2026-09-20 (card c-314, requirements V2, V3 and the three paths of V10 in
`<install>/history/docs/voice-next.md`). One press opens a conversation and the microphone reopens after
every answer, until the user says "that's all", taps to pause, or a minute goes by with nothing
heard. It sits on top of the detector above: **without one there is no conversation mode**,
because a conversation is a microphone something else has to close.

**One state machine, two new states.** The orb's states were `idle`, `listening`,
`thinking`, `speaking` and `down`, read from `state.bus.state`. `paused` and `partial` are
additions to that one machine, not a second one, and `displayState()` in
`segments/voice/app/app.js` is the only place that decides which word wins: `down` beats
`paused` beats `partial` beats the bus. A socket that is gone makes every other word a
lie; a closed microphone is not listening whatever the bus last said; half a held sentence
is what the orb should be saying while it waits for the rest. It is `partial` rather than
`held` because `turn.held` already means "Harbor answered while you were talking".

**Who owns which clock, which is what `AUTO_LISTEN_MAX_MS` became.** The gateway ends an
utterance (the hangover) and ends a listen nobody spoke into (`[voice] VAD_QUIET`, 20 s,
which is today's page backstop moved to the side that has the audio). The page's own timer
is no longer what ends a hands-free turn: with a detector it is a 90 s failsafe for a
gateway that went quiet, and with no detector it stays exactly the 20 s it was, because
then the page really is the only clock there is. **A finger on the orb has no cap** (c-424,
2026-09-23): push to talk ends when the user lifts it, and the 20 s used to be armed by every
press, so a long sentence held under the user's finger was released mid-word. A real press gets
only `STUCK_POINTER_MS` (180 s), for a pointer whose `pointerup` never arrived, and a
release by any of the three timers is traced as `failsafe-stuck`, `failsafe-detector` or
`failsafe-auto`, so the log says which one fired (`tests/fixtures/voice-listen.js`, checks
9 and 10). **A lost release sends no room audio** (lane D review, item 3): the stuck guard,
the window's `blur` with Space held, and the orb's `pointercancel` and `pointerleave` (iOS
cancels a touch for an edge swipe or an incoming call; round 2, item D) all end the hold
with `cut` through `dropHold`, which drops the listen, never with `end`, which would send
whatever the microphone heard since the user stopped meaning to talk (check 12). The gateway has no length cap on a push-to-talk listen either: its quiet cap
applies to a hands-free one only. A quiet cap is needed at all because the
hangover cannot fire without `VAD_MIN_SPEECH` of real speech first: silence that was never
preceded by a word is not the end of an utterance, it is an open microphone.

**Presence is what the page can see, not an open socket** (D-2, c-438, 2026-09-23). A
phone with its screen off keeps its WebSocket, so `Gateway.is_live` (a socket open now, or
any message within `PRESENCE_RECENT_SECONDS`, 45 s) read a pocketed phone as the user
listening. The page now says `{"type": "presence", "visible": bool}` on every
`visibilitychange`, `pagehide` and `pageshow` and on every socket open, whatever it is
doing (it used to report hiding only during a conversation or a hold, by pausing).
`Gateway.page_presence` writes it per socket, only while that socket is still connected
(a late message from a closed page is dropped, review item 8), and logs a `presence` record, and
`Gateway.attending` is true while some connected page has not said it is hidden (a page
that never says, an older one, counts as seen). It gates ONLY speech nobody asked for:
`Dispatcher.announce` and the pin's expiry line (the unpin itself still happens). An
answer to the question the user just asked still goes by `is_live` and, when the user has gone, by
the silent path the user already has (V9). Like the trace (V13-G11), the message is a fact and
never a command: its branch in the socket loop calls `page_presence` and nothing else, so
it can hold speech back and can never start anything.

**A page that goes away takes its own conversation with it, and nobody else's.** A
conversation belongs to ONE socket, the page that last said `conversation: true` on a
`start`, and `Conversation.owner` is that socket. `Gateway.client_gone`, reached from
`drop_client` so a failed send and a closed tab leave the same way, closes that page's
conversation, cancels a held partial's timer and decides what happens to the held words.
Without it only an explicit `pause` clears the flag, so a
killed tab leaves the conversation open and a timer running that later dispatches a
Harbor turn, or files a card, for a client that is gone. A page that describes a close
like this before the code has it is the case the rule "where a page and the code
disagree, the code wins and the page is the bug" is for.

**The user's half sentence is kept when that happens, and it is kept differently by mode.** In
CAPTURE it is filed, because a capture needs no listener and losing a dictated idea is
the thing capture exists to prevent. In TALK it becomes a quiet turn: the transcript line
is kept and no Harbor turn is spent, because an answer spoken into an empty room is the
one thing it must not become. Either way the judge's call line gets its `abandoned`
outcome, which is exactly what happened to it. The conversation's own messages (`listen`,
`partial`, `conversation`) are sent to the owner rather than broadcast, so a second open
tab is never told to arm a microphone nobody is talking into.

**Three quiet windows are V2's minute of silence**, as ONE number rather than two that
have to agree: `CONVERSATION_QUIET_LIMIT` (3) times `VAD_QUIET` (20 s). It is also the
runaway guard, and that is the failure this part is arranged around: a page that reopened
a microphone for ever in the user's pocket is the worst thing this slice could do. A microphone
that will not open ends the conversation rather than asking the platform again, and so
does a dropped socket.

**The page numbers its listens and the gateway echoes the number.** Conversation mode
re-arms after every answer, so for the first time there is such a thing as an `endpoint`
for the listen BEFORE the one in hand, which would end the new one a syllable after it
opened. `start` carries `listen`, `endpoint` carries it back, and the page drops anything
that does not name the listen it is in. A pause retires the listen before it closes
anything, so a tap racing an endpoint wins by that same staleness check rather than by a
rule of its own.

**A `quiet` endpoint is answered with `cut`, not `end`.** Nothing was said, so there is
nothing to dispatch, and `end` stays the only thing that flushes a buffer.

**Paused means the microphone is CLOSED, not muted** (V3): stopped tracks, a closed
capture context, the `mic` record dropped so the next open is fresh, and the phone's own
recording indicator off, which is the only honest signal that nothing is being captured.
The PLAYBACK context is never closed, because iOS unlocks an `AudioContext` on a gesture
and a closed one needs a new gesture before it can make a sound again. Between the turns
of a live conversation the page stops sending rather than tearing the stream down:
re-arming a torn-down stream needs a `getUserMedia` the platform may only grant from a
gesture, and there is no gesture between two turns of a conversation. Nothing is buffered
either way, and the honest cost is that the recording indicator stays on while a
conversation is open, which is true.

**THE GATEWAY SPEAKING IS NOT A PAUSE, and V3's promise is still kept.** V3 lists the
gateway speaking among the automatic pauses, and the code does something different on
purpose: while it speaks, the page simply stops sending (the worklet drops every frame
unless `state.holding`) and the stream stays open, because tearing it down would need a
`getUserMedia` to re-arm and iOS may only grant that from a gesture, of which there is
none between two turns of a conversation. Nothing is captured and nothing is buffered
either way: the page sends nothing, and the gateway's buffer is reset by the next
`start`. "Paused means the microphone is CLOSED" is a promise about THE USER'S pause, the tap,
and that one really does stop the tracks. The visible cost is that the phone's recording
indicator stays on for as long as a conversation is open, which is true, and it goes off
the moment the user pauses or it ends.

The real automatic pauses, which do close the microphone, are the app leaving the
foreground (`visibilitychange` and `pagehide`), an audio context iOS has interrupted (a
call, Siri, the control centre: Safari moves the context to `interrupted` or `suspended`
and never moves it back, so the page pauses visibly rather than sitting in a conversation
with a dead context), the quiet cap, and the socket dropping. Coming back does not resume
by itself: a resume opens a fresh listening window, and that is a thing the user asks for with a
tap. The screen wake lock is held only while a conversation is live, and it is re-acquired
only by that tap.

**What a tap on the orb means depends on one thing only: whether a conversation is open.**
Outside one it is press and hold, exactly as it was. Inside one the microphone is already
open and the detector ends the sentence, so the tap is free to mean pause, EXCEPT while it
is speaking, where it is still the cut plus the next question in one gesture: barge-in does
not change. The orb's label says which at every moment.

**The way in is `?listen=1` or Conversation in the composer's + menu** (the control under
the orb until VP-2). The hands-free URL opens a
conversation now (the user's call at c-314's plan gate: that shortcut exists because the user did not
want to hold the button, which is what conversation mode is), and `?listen=once` is the
single hands-free utterance it used to mean, which is what the Capture shortcut points at.
Conversation mode works in Capture as well as Talk: five ideas dictated in a row is the
same motion.

**The two conversation words are tables, matched before anything is dispatched.**
`verbs.END_CONVERSATION` ("that's all") and `verbs.PAUSE_CONVERSATION` ("hold on") are
whole utterances matched like the one board question, so nothing that merely contains the
words can trip them, and matching them in the gateway is what stops the words that end a
conversation costing a Harbor turn. `config.flags_for_page` serves the same tables to the
page as its floor, so there is one table and two readers rather than two tables.

### The listen watchdog, and what the orb is allowed to claim (V13, the page half)

The case it answers: Harbor connects the user to a house and the orb reads
"listening" for a minute with no audio behind it. A push-to-talk press then works
first time, which is most of the diagnosis: the microphone is available, and what
failed is the automatic re-arm. Nothing the page can SEE has failed at all. `openMic`
resolves because `mic.node` still exists, `state.holding` is true, and the only untrue
thing in the system is the word on the orb. The repair (c-314):
if the microphone will not reopen on iOS after the gateway's message, arm the
listen from the user's tap instead.

**The page watches the frames, not the microphone.** Every message from the capture worklet
counts, including a frame of pure silence, because the question is whether the PIPE is
moving and not whether anyone is speaking: a quiet room still moves samples. Three seconds
of an automatic listen with no frame at all is the failure. The page spends the cheap repair
once, which is the same `press()` path with `closeMic()` in front of it so `getUserMedia` is
really asked again rather than returning the stream whose tracks have ended, and if that
produces nothing either it stops claiming to listen. It keeps watching after the first frame
too: a stream that dies mid-listen says the same untrue word as one that never started. A
press the user's finger made is not watched, because the user is watching it.

**A stall is a pause with a fault behind it, and one tap repairs it.** `micStalled` sets the
word and then goes through `pauseVoice`, so everything a pause promises is kept here as well
(stopped tracks, the listen retired so a late endpoint cannot land on it, the gateway told,
the phone's recording indicator off). The conversation is deliberately left OPEN, because
ending it would make the user start it again as well as tap. The orb reads "Microphone stalled,
tap to reopen", and that tap presses INSIDE the gesture rather than through `resumeVoice`,
which would defer the `getUserMedia` behind `whenPlaybackEnds` and spend exactly the
activation iOS is waiting for.

**Which is also what an automatic press that cannot open the microphone now does.** Ending
the conversation there, which is what c-314 built, answers "iOS wants a touch" by throwing
the conversation away when one touch would have repaired it. A press THE USER'S FINGER made that
still cannot open the microphone is the other case and it still ends the conversation,
because a platform that has refused a real gesture has refused the only thing there was left
to try. Neither path arms another listen: asking a platform that just refused is how a retry
loop starts.

**"Listening" is a claim about audio, so it waits for audio.** `displayState()` is still the
one place that decides, and it gained two words: `stalled`, which beats `paused` and says
which of the two it is, and `opening`, which is what a hold reads before its first frame.
While the page is holding it trusts itself over the bus, because whether audio is leaving
this phone is a fact only the page has, and the bus state is the gateway's word, up to one
poll old.

**Every player is asked before the microphone reopens, and none of them may hold it open for
ever.** `whenPlaybackEnds` used to compute one wait at the top and then poll
`speechSynthesis.speaking`, which missed three things: a chunk arriving during the wait, the
gap between a queued `speak()` and the voice actually starting (V8's sequencing point can
delay one by a whole bufferful), and a synthesiser that never reports back at all. It is now
one loop that asks the scheduled queue (the TTS chunks and the gateway's tone are the same
`out.at`), the page's own outstanding utterances, and the browser, until all three are
quiet, and only then serves the 250 ms re-arm guard. Twenty seconds after the last thing was
handed to a player it gives up and treats playback as ended, and says which of the two it
was in the trace below.

**And the page says what it did, in a line the gateway only logs.** `{"type": "trace",
"event": ..., "reason": ..., "listen": ..., "at": ...}` at each of `arm`, `press`, `frames`
(once per listen, on the first frame), `playback-end`, `quiet`, `stalled`, `release` and
`repress`, with `at` in milliseconds since the page loaded. It exists because this failure
leaves no trace anywhere on its own: the gateway sees a `start` and then silence, and cannot
tell a page that never opened a microphone from a man who said nothing. Nothing waits on it
and nothing branches on it, so a gateway that has never heard of the type drops it and the
page is correct against both halves of a rolling deploy. The other direction is
`{"type": "listen-now", "reason": ..., "generation": ...}`, the gateway asking for the
microphone by name after it has connected the user to a house: it goes through the same automatic
press every other re-arm goes through, inside a conversation only, never over a pause or a
stall, and never for a generation the user has already moved on from.

**The page opens a door for its own test.** `?selftest=1` (or `selftest` in flags.js) hangs
`window.__voiceTest` on the page: the state, the entry points the socket and the user's thumb
already reach, the bar's label, and one function that delivers a worklet frame.
`tests/fixtures/voice-listen.js` loads the page's scripts, in `index.html`'s order, under
node with a stand-in DOM, socket and
clock and drives the whole path, the way `tests/fixtures/board-*.js` run the deck's board,
because a screenshot cannot prove that three seconds of silence re-pressed the orb once and
only once. The door is a read plus entry points the socket already has, so it adds no power,
and it is shut on every page that does not ask for it.

### The three paths a verdict reaches, and why they are here

V10 says the paths a verdict needs must exist from the start, because they are the
expensive retrofit. c-324 built the `preturn` seat; this card built what a verdict
reaches. **Every one of them is entered only when `Ruling.by(...)` says `jev`**, and in
`off` and `shadow`, which is what every key ships as, every answer's source is `rule`. So
on day one none of these is entered, and that is a mechanism rather than a promise: it
takes a key going `on`, which is refused while a judge has no floor, or `judges.pretend`
in a test.

- **`complete: no` HOLDS the utterance.** Nothing is dispatched, `{"type":"partial"}` and
  `{"type":"listen"}` go down, the orb reads "Go on", and the next utterance is joined to
  the held text before anything is asked. The held half carries the mode and the space it
  was SPOKEN in, so a half dictated into Capture stays a capture even if the toggle moved
  while it was held. It expires after `config.JUDGE_HOLD_SECONDS` (4 s, the judges' own
  number, not a second one) into the ordinary turn it would have been, and **a joined
  sentence is never held again**: one wrong verdict costs one pause, never a chain of
  them, and never a lost sentence.
- **`addressed: no` ends the turn QUIETLY.** `Dispatcher.quiet` begins a turn, writes the
  transcript line and finishes it with no answer, no speech and no Harbor turn spent.
  Nothing is said aloud, not even an acknowledgement: saying "I will let that one pass" to
  a man who is talking to somebody else is exactly the interruption the verdict exists to
  avoid. The same path carries the conversation words.
- **`route: board_read` is answered off the board.** The reply path that does not pass
  through Harbor already existed as the instant tier; what changed is who decides.
  `Dispatcher._instant` now takes the route, which is empty unless Jev decided it, so with
  the rule judge it reads exactly as it did. `verbs.BOARD_READS` names c-300's five reads
  and exactly one of them, `needs-you`, has a renderer today (the user's call at the plan gate:
  this card builds the path, the other four renderers are a follow-up). A board read with
  no renderer falls to Harbor and is logged as `board-read-unrendered`, because answering
  "what is building" with the contents of the queue would be the confidently wrong answer
  this package is arranged to refuse.

**The outcome lines are what make the shadow log readable.** `judges.outcome` is written
where each outcome is KNOWN: `carried-on` when a held half got the rest of itself,
`abandoned` when it expired instead, `barged-in` when the user pressed over an answer,
`ended-quietly` for a turn that ended without one, and `answered` for an ordinary finish.
Without them the log has calls and no verdicts about the calls, and the report V10 exists
to produce cannot be read.

**Where it all is.** The page half is `segments/voice/app/voice.listen.js` (the
conversation, the listen numbering), `voice.audio.js` (`closeMic`) and `voice.view.js` (the
display state), with its control in `index.html` and its states painted in `app.css`. The gateway half is `server.py`: `Conversation` holds the open
flag and the held half, `Gateway.turn_over` is the one place a microphone reopens by itself
(called by the dispatcher when a TURN ends, not when a speech ends, or a narration line
would reopen it mid-turn), and `Gateway.dispatch` is the one place a turn starts now that
it is reached two ways.

**What proves it.** `tests/test_voice_conversation.py` holds the page's rules as greps, in
the style of `tests/test_voice_css.py` and for the same reason: a stdlib suite cannot open
a microphone, and the render and the live socket are the proof. `bin/keel-voice-selftest`
drives the gateway half, including all three verdict paths through the fake judge, and the
live check ran a real spoken turn through a scratch gateway on its own port under its own
`KEEL_HOME` with a fake `kb`, never the live board.

## Connected to one card's house (V4, V6)

Built 2026-09-20 (card c-315, requirements V4 and V6 in `<install>/history/docs/voice-next.md`). "Connect me
to c-272" pins voice to one card, and from then on what the user says is taken as a turn by the
house that did the work, in its own session, with its own tools and its own worktree. The user's
words land in the real transcript, so "merge phase two into phase one" is an edit to the
plan by the house that wrote it, and the card's gates do not move.

**One verb, both Harbors.** `keel converse <card> "<text>"` (`keel/converse.py`) is the
primitive. Voice runs it through `voice/harbor_voice/connected.py`; the phone Harbor runs
the same command when the user asks about a card, so only the ANSWER enters that conversation and
never the plan. Three forms, and the first is the whole of it:

| Command | What it does |
|---|---|
| `keel converse c-272 "merge phase two into phase one"` | one turn, prints the spoken answer |
| `keel converse c-272 --connect` | take the hold and pin, no turn, no tokens |
| `keel converse c-272 --release` | let the house go and wake it (back to Harbor) |

`--json` carries the same answer with `held_until` beside it, which is how the page knows
when its pin runs out. A refusal is still a sentence and still exits 1: whoever ran it is
holding a microphone open, and what it needs is words to say.

**What one connected turn costs, measured** (2026-09-20, Claude Code 2.1.278, on the Linux host;
the probe scripts and logs are on the card, `state/cards/c-315/probe/`). Stop the house's
process 0.8s, the headless turn 5.0s on a 237 KB transcript and 6.7s on an 889 KB one (the
model's own answer is most of that, and every `-p --resume` re-reads the whole transcript),
the wake 0.9s. So Keel's own overhead is under two seconds, and NONE of it repeats between
the turns of one conversation, because the house is held down for the whole of it.

**And what it costs since V12** (2026-09-21, the same build of `claude`, on macOS;
`<install>/history/docs/probes/conversation-probe.py`). While the user is PINNED the sentences no longer each start
a process: one kept-alive `claude` takes all of them, and 3.6 to 4.1s to the first word
becomes 1.0 to 1.5s. The answer is no longer waited for either, so the first sentence of a
four sentence answer is spoken at 2.2s where the whole thing used to be spoken at about
5.2s. The stop and the wake are unchanged, and they still happen once per conversation.

**The shape, and why it is this one.** `claude -p --resume` is refused while the session's
background process is alive, so the phone door and the headless door are exclusive in time:

1. the house's process is stopped, once, when the conversation starts;
2. the hold goes on the card;
3. every sentence goes into ONE kept-alive `claude` for the whole conversation (V12), under
   the card's own settings file, model, cwd and add-dirs, opened when the user connects and closed
   when the user is done. A turn is one line written to its stdin and one `result` record read
   back, so nothing is polled and nothing raced. A sentence with no pin behind it (the phone
   Harbor's single question) is still one `claude -p --resume` of its own, and so is every
   sentence when the kept-alive path is unavailable;
4. each exchange leaves one short note on the card, the user's words verbatim;
5. the conversation is CLOSED, and then "back to Harbor" (or the hold running out) wakes the
   process with `claude --resume <id> --bg`, NO flags and NO prompt, which keeps the same
   session id, the same saved options and the same `claude.ai/code` link, and costs no
   tokens. The close comes first because the wake is refused while anything holds the
   session.

The last one is why the card's "Open in Claude app" link does NOT churn. The 2026-09-18
probe expected it to, because a resume WITH flags mints a copy under a new id, which is
what `house.resume` does on purpose. `harness.wake` is the flagless form, and
`tests/fixtures/harness/README.md` carries both recordings.

**Only the connected turn may take the lock.** `options.voice_hold` is refused to any
actor but `voice`, `drain` and `human` (`board.HOLD_ACTORS`), and a house cannot name
another actor to get around it: a process carrying `KEEL_CARD` is a house and `--actor` will
not lift it out of that (`cli.resolve_actor`). The reason is the same one that makes the key
useful: a held card is skipped by the drain and by the Stop hook's nudge, so a house that
could set it on its own card would be making itself undrainable in one line, and `kb` is on
every house's PATH. The verb itself is the other door and it is shut the same way: `keel
converse` refuses to run at all under `KEEL_CARD`, because it takes the hold without going
through `kb`, and a house talking to a house is not what V6 asks for.

**The user's Stop tap wins, and leaves the house down.** Stop is the one place a human ends a
session on purpose, so a hold is not a reason to refuse the user: the tap releases the hold, stops
the session, notes that it was stopped while voice was talking to it, and wakes nothing. The
gateway finds out on its next turn, because the verb answers `unpin` when the hold a pinned
caller was holding has gone (the user's Stop, the user's answer at a gate, or the drain clearing one that
ran out), and the pin is dropped rather than quietly retaken.

**The lock is one key on the card.** `options.voice_hold` ({at, until, stopped, turns}):
Keel has one store, so the thing that says "the user is talking to this house" is a field on the
card and nothing else. Everything that could move a house reads it: `drain.reconcile`,
`drain.retire_tracking`, `drain.resume_quiet`, a relay the deck tapped, `house.resume`, and
both bodies of the Stop hook. It carries an expiry ([keel] `voice_hold_seconds`, 300), and
`drain.release_holds` is the repair: a conversation the user walked away from is cleared and the
house is woken on the next pass. A house voice found ALREADY down (a tracking card's
retired session, a done card) is left down, because waking it would only give
`retire_tracking` the same session to stop again.

**The three guards, and the one that needed a probe.**

- **Idle only.** A house mid-work is refused ("it's building right now"), and the user's question
  is left on the card as a note it sees at its next turn. Two turns in one transcript is
  the race the hold exists to stop.
- **The drain waits.** Above. The user's own answer at a gate is the exception: Approve and Send
  back pass `force=True` and RELEASE the hold rather than being refused by it, because a
  human answering a gate is plainly finished talking.
- **Voice-aware hooks.** A connected turn fires the card's Stop hook like any other turn
  (probed; it was not recorded anywhere before). Without this guard `kb stop-check` would
  answer it with `{"decision": "block"}`, which does not merely spend one of the two
  nudges: a block decision sends the house back to WORK, mid-sentence. So `board.stop_check`
  and `ending.check` both return early on a held card, and the hook is recorded with
  `voice_hold` so the record says why nothing happened.

**The framing says the words were SPOKEN.** `prompts.converse` tells the house three things
it cannot work out for itself: the answer will be spoken (sentences, no markdown, no paths),
the user's words came through speech recognition and may be misheard, and therefore anything
destructive or hard to reverse (deleting, force-pushing, merging, staging or approving the
card, spending money, sending anything outward) is said back and waits for a spoken yes.
Reading, explaining and editing its own plan or its own worktree need no confirmation: that
is what talking to it is for. A DONE card has no worktree (the merge reaped it), so the turn
runs in the card's own directory and the framing says it can explain but not change; the
stage is what decides that, never a look, because `house.placement` CUTS the worktree it
names.

**The verb is a phrase table plus a card id, and it is the FLOOR rather than the only
way in** (c-419 added the other one, below). `verbs.CONNECT_OPENINGS` is
the openings ("connect me to", "put me through to", "talk to"), matched at the start of the
whole utterance, and what follows must read as a card id: `verbs.card_id_in` takes "c-272",
"c 2 7 2", "card 272", "two seventy two" and "three fifteen" and answers the board's own
spelling. "Connect the speaker to the amp" reaches nothing, because "connect the speaker to"
is not an opening and "the amp" is not an id. `verbs.DISCONNECT` is "back to Harbor" and its
neighbours, matched against the whole utterance the way `WAITING` is; going OUT is read more
leniently than coming in since 2026-09-21 (`verbs.leave_intent`, below under "Leaving in the user's
own words"), because an id is what makes the way in safe and there is nothing to parse on
the way out.

**Where the phrases sit in the turn.** Before the `preturn` judge and before anything is
dispatched, beside the two conversation words: they are not questions, and no verdict of any
kind may move them. While a card is pinned, `Dispatcher.rule_route` answers `connected`,
the judge's `route` menu is handed a fourth option for exactly those turns (`judges.ask`'s
`criteria`, which exists for a menu the caller owns), and the seat IGNORES a `route` verdict
entirely, because a `board_read` answer must never take a sentence away from the house the user is
talking to. A capture is still a capture: the mode is the message's.

**The page names the card.** `?connect=c-272` opens the page already connected, which is
what the deck's "Talk to this house" button links to; it is a launch instruction like
`?listen=1`, dropped from the URL and never remembered, because a pin is a conversation and
not a preference. The header carries the card while connected and the same button is a tap
back to Harbor; the orb reads "Hold to talk to c-272". The pin is the GATEWAY'S fact, drawn
from `{"type": "connected"}` and from the bus, so a page that opens mid-conversation reads
it correctly and a page can never pin itself.

**On the deck.** "Talk to this house" sits in the card pane beside Open in Claude app,
Resume house and Drop in. While a hold is live the card shows an "on voice" pill where the
app link would be (that link cannot work until the house is woken) and Resume house is
absent. `house.converse` is the same turn as a verb, for a turn typed from anywhere else.

**What is refused, and it is refused out loud.** No house session yet (with the offer to
start it), an archived card (there is nothing to talk to), a house that is building, and a
machine under its memory floor (a turn is a whole `claude` process, and one that gets the
machine OOM-killed would take the gateway with it). Each of those leaves the user's question on the card.

**Bosun is the one target that is not a card** (c-523). "Put me through to Bosun" and a
connect directive naming `bosun` pin the gateway to `bosun`, and `keel converse bosun` runs
the same hold on Bosun's session through `keel/bosuntalk.py`, with its hold on the board's
`holds` row instead of a card; [Bosun](96-bosun.md), "Harbor and Bosun", has the whole of it.
Harbor's answer to one of Bosun's asks rides the same kind of keyed directive
(`<<keel-answer a-31 A key>>`) and is recorded by the page, never by the gateway.

**A turn that wedges takes its children with it.** A connected turn is the one thing Keel
waits on for minutes, so it runs in its own process group (`harness.run_alone`) and the
GROUP is killed when it overruns: SIGTERM, two seconds, SIGKILL. `subprocess.run(timeout=)`
kills the process it started and nothing that process started, which on a 12 GB machine is the
leak `bin/keel-browser` exists to prevent, in the memory the gateway's latency is measured
in.

## One process for the whole conversation, and an answer the user hears as it is written (V12)

Built 2026-09-21 (requirement V12 in `<install>/history/docs/voice-next.md`). Two costs went, and both were
Keel's own rather than the model's: a `claude` started per sentence, and a gateway that
waited for the whole answer before speaking any of it.

**Who owns the process.** `keel converse` is a CLI run once per sentence, so it cannot own
something that has to outlive the sentence. The owner is the long-lived `keel serve` on this
machine, the same process as the deck. `keel/housetalk.py` holds the registry, one live conversation per card id,
each with its own lock so two sentences can never read each other's records; `keel/housetier.py`
is the seam: `POST /api/house/open` warms one for no tokens, `POST /api/house/say` takes one
turn and STREAMS the answer back one JSON object per line, `POST /api/house/close` ends it,
and `GET /api/house` says what is open.

**These routes start a `claude`, and everything about their shape follows from that.** The
first cut took the whole placement from the request body (cwd, config dir, settings file,
model, add-dirs, tools, session id), with no key, on a server reachable
from the tailnet: any device there, or any page open in a browser on one, could have started
a process with its own prompt and its own tools. Four rules now, each closing a different
half of it:

1. **The body names a CARD**, plus the user's sentence, the turn id and the timeout. The server
   reads that card off its own board and builds the plan itself, and wraps the sentence in
   its own `prompts.converse`: a caller that could choose the framing could delete the
   misheard rule, which is the paragraph between a wrong word and something irreversible.
2. **The board decides whether there is a conversation at all:** a live `options.voice_hold`
   (which only `voice`, `drain` and `human` may write) and a card with a house session.
3. **A machine-local key**, `<state>/house.key`, 0600, minted once, carried in
   `X-Keel-House` and compared with `hmac.compare_digest`. A custom header also forces a
   preflight on a cross-site request, and the preflight is never answered.
4. **Local only:** anything carrying `X-Forwarded-*`, `X-Real-IP` or a `Tailscale-` header
   is refused with this machine's key, because there is no legitimate hop.

**Asking twice asks the house once.** A sentence written to the process cannot be
un-written, so a client whose stream broke must never simply ask again: it would spend a
second turn and the user would hear the answer twice. Every turn carries an ID, the server keeps
the turn in flight and the one before it with every event each has produced, and a `say`
naming a turn it already knows ATTACHES: the caller is handed the events after the `seen`
it says it has had, follows the rest live, and gets the same result. The client retries the
same id once on a broken stream and fails out loud on the second. The one-shot fallback is
left only where the user's sentence cannot have reached a `claude`: nothing listening before the
request was accepted, the board refusing, the write itself failing, or the process confirmed
dead (that last one does fall back, because an answer matters more than a duplicate line,
and the card says which happened).

**The three waits nest, innermost first.** The server ends the turn at `timeout`, the HTTP
client gives up at `timeout + 10` with a 30 s read timeout, and the gateway kills the
`keel converse` CLI at `timeout + 30`. They were inverted in the first cut, so a turn that
overran was reported by the layer that knew least about it. A quiet turn writes
`{"type": "alive"}` every ten seconds, which is what makes a 30 s read timeout safe on a
turn that thinks for two minutes, and what notices a dead server.

**The board half and the machine half.** `keel/converse.py` keeps everything only the board
can answer: the guards that read the card, the hold, the notes, and the sentences the user hears
when a turn cannot be taken. `keel/housetalk.py` is everything about the machine: busy,
the memory floor, stopping the house, owning the process, cutting the answer up. It takes a
plain `plan` dict (the session id, cwd, config dir, settings file, model, add-dirs, whether
there is a worktree) and yields plain JSON-able events, and it imports no board at all. That
is what lets the board half reach it through a plain HTTP transport rather than a shared
import.

**The framing is said once.** `prompts.converse` wraps the FIRST sentence of a conversation
in the three paragraphs a house cannot work out for itself; every later sentence is
`prompts.converse_more`, the user's quoted words and nothing else, because the rest is already in
the transcript. The machine half picks between the two, since only it knows whether the
session is new.

**The answer is cut into sentences as it arrives.** `keel/sentences.py` is a pure cutter:
a full stop ends a sentence only when whitespace follows it, which is also what makes a stop
at the end of the buffer WAIT rather than guess ("it took 4." may become "4.2"), and never
inside a code span or a fenced block, and never after a known abbreviation. A blank line, a
list item, a heading and a line ending in a colon each end a part; an ordinary wrapped line
does not. Nothing is longer than 200 characters. Markdown is stripped, because asterisks
and backticks read aloud are syllables.

**A fenced code block is never spoken and never capped.** Reading one aloud is unbearable
and reading half of one is worse, and the cap did exactly that in the first cut: a long
block arriving in small pieces grew past 200 characters and was cut at a space. A fence now
leaves the cutter as its own `fence` event carrying the info string and the raw body, with
one line in its place ("There is a code block in my answer, it is on the page."), at most
once per answer. An unclosed block at the end of a turn is treated the same way. The event
travels the stream as `{"type": "fence", "lang": ..., "body": ...}`.

**And a fence whose language is `board` is DRAWN.** That is the hook the event was kept
generic for, and it is built ([the board](45-board.md)): the body is the board's own line
language, `keel/boardpen.py` pushes it to that card's board as the fence closes, and the
sentence in its place is built from the push REPORT rather than decided by the cutter: "I
have put that on the board." only when it landed, and otherwise what did not land and why
(C1, 2026-09-23). Once a board block has closed the cutter speaks nothing more of the
answer (N7: a drawing is never explained live); the rest is on the card.
A house in a voice conversation has no shell to run `keel board push` in mid-sentence, so
this is how it draws while it is still talking. A one-shot turn has no stream to cut, so the
same blocks are taken out of the finished answer instead (`sentences.board_blocks`), which
is also what keeps a block out of the user's ear when the question came from the deck.

**HARBOR DRAWS THE SAME WAY (2026-09-21).** Its answers do not come through `keel converse`
at all, so until stage three a `board` block in one of them was read as a code block and
thrown away: asked out loud to draw, Harbor filed a CARD asking a house to do it. The turn
in `voice/harbor_voice/harbormsg.py` now reads its own answer through the SAME pen
(`voice/harbor_voice/drawing.py` imports `keel/boardpen.py`, one stdlib-only file deep, the
way `harbor_voice/index.py` imports `keel/deckdigest.py`), with a source of `talker`, and
pushes with the verb: `keel board push --talker --file <ops>`. The verb rather than the
store, because only the verb knows which board this checkout writes to. `run_turn` hands
back the RAW answer for that reason: a block whose newlines have gone is no longer a block,
so the collapse to one spoken line happens after the pen, on what is left. An answer with no
block in it is unchanged, byte for byte.

**How a part reaches speech.** Down the channel that already existed. `keel/narration.py`
writes it into the voice gateway's progress inbox, the one the watch loop is already
claiming for this turn, with `part: true` and no `action`. The dispatcher tells the two
apart by that: a narration line still waits for the four second silence gate, the repeat
rule, the per-turn budget and the shape guard, and is spoken in Harbor's voice; a part is
spoken at once, in the HOUSE's voice, because the house said it (V8). The first part sets
`answering` on the turn, so a line about what the house is doing can never land in the
middle of the answer. The final answer is then NOT spoken again; it still reaches the page,
the transcript and the card. The one exception is a turn the user barged into: the parts stop, the
turn remembers that it was cut, and the whole answer is spoken once the user is quiet, because
half an answer heard is not an answer heard.

**"The user has already heard it" is a CHECKED FACT, not an assumption (V13, 2026-09-21).** The
paragraph above is what V12 built and it was half true in a way that cost the user most of two
answers. `_say` blocks for the length of the audio: while part one played, the remaining
parts landed in the progress inbox and the final answer landed in the say inbox, and the
watch loop claims the SAY inbox at the top of every pass. So it took the result, saw that
`spoke_parts` was non-empty, and finished the turn silently without ever claiming the parts
it had not spoken. A turn so cut speaks one
sentence of two and records `spoken: false, reason: "the answer was spoken as it
streamed"`, and its second sentence surfaces at the NEXT turn as a `dropped` line on the
progress channel; a longer answer loses four the same way (both seen in one transcript). The selftest could not have
seen it, because its `speak` returned instantly and there was no window for anything to
land in. Three things repair it:

- **The progress inbox is drained once more before a house turn may finish**
  (`Dispatcher._drain_parts`), under exactly the checks a part is spoken under anywhere
  else: the generation and liveness, with a refusal latching `parts_cut` as usual. A
  narration line found there is refused rather than spoken, because the answer is over.
- **A barge-in is latched at the top of every watch pass** (2026-09-24), before the `say`
  inbox is claimed: a turn that spoke parts and whose generation has moved is `parts_cut`.
  The latch used to sit below the claim, so an answer that landed within one tick of the user's
  barge-in was taken as a remainder of parts the user had cut off and only its tail was spoken.
  Under load the tick stretches and so did that window; the selftest holds the watch loops
  at `pass_gate` while the user moves on and the answer lands, so the next pass sees both.
- **What was spoken is compared with the final answer** (`dispatcher.answer_left`). The
  cutter strips markdown off every part and the final answer keeps it, so the comparison is
  on what can be HEARD: `verbs.as_heard` takes the markdown off and `verbs.heard_key` keeps
  a map back into the real text. A prefix speaks the REMAINDER, taken as a slice of the
  answer's own words rather than rebuilt from the parts; nothing spoken, or a prefix that
  does not match, speaks the WHOLE answer, because taking a remainder off a wrong prefix
  would cut a sentence off at its start. Only a real cover finishes silently, and it is
  recorded as `covered: true` or `remainder: <n>` so the two are told apart afterwards.
  **Both sides are the SPEAKABLE form** (2026-09-24, lane H): `verbs.without_code` puts the
  cutter's own stand-in (`verbs.FENCE_SAID`, held equal to `sentences.FENCE_SAID` by a
  test) where the first code block was and drops the rest and any `board` block, as the
  cutter does. Before it, an answer with code in it never matched its own parts, because
  the final answer arrives collapsed to one line with the code inline, and it was spoken
  again whole, code included; the remainder and the whole answer spoken from here never
  carry a block now either (`tests/test_voice_stages.py`, driven through the watch loop).
- **A part that arrives after its turn is over is logged as `late-part`** with the turn it
  belonged to, rather than as a generic drop on the next turn. Four `dropped` lines on the
  progress channel read as narration going missing; what had gone missing was the answer.

**A house that speaks and then goes back to work gets its narration back.** Ending the
narration at the first part, full stop, silenced the whole of a long turn whenever the house
opened with a line of its own ("Let me check that file.") before picking up a tool. An
`action` arriving AFTER a part says that text was a PREAMBLE and not the answer: the
narration reopens until the next part, and the parts spoken before it stop counting as the
answer, so what the no-double-speak rule compares against the final result is the LAST
message's parts. A narration line written BEFORE the answer started and claimed after it is
still refused rather than spoken over the answer, and the two are told apart by the clock
that wrote them, which is `keel converse`'s own in both cases.

**Every exit closes the conversation before the wake.** "Back to Harbor", the drain clearing
a hold that ran out, the deck's Stop on a held house, and a gate answered while held: each
calls `housetier.close_session` first, because `claude --resume <id> --bg` is refused while
anything still holds that session. The drain and the deck run in their own processes, which
is exactly why the close is an HTTP call to the owner rather than a method. The conversation
has the hold's own idle deadline (`voice_hold_seconds`) and a reaper in the server closes
one that has gone quiet. A `keel serve` that exits closes its conversations, and one that is
killed still leaves none behind: the `claude`'s stdin is that process's pipe, so it ends by
itself (probed).

**When it cannot be used.** A server that is not answering, a conversation that will not
open and one whose process dies mid-sentence all fall back to the one-shot `claude -p
--resume` of V4, and the conversation carries on one turn slower. The exception is a
conversation that died AFTER some of the answer had been spoken: asking again would pay for
a second turn and speak the beginning of one answer followed by the whole of another, so
that turn fails out loud instead. `[voice] kept_alive = false` turns the whole thing off.

**What the Stop hook does here.** It fires PER SENTENCE, exactly as it does for a one-shot
turn (probed 2026-09-21: three sentences, three payloads). So guard 3 is unchanged and both
Stop hook bodies still have to recognise a held card.

### Harbor's own turns, kept alive and streamed (R2, behind a flag, on since 2026-09-24)

V12 gave a connected house one kept-alive process; Harbor's own turns stayed one cold
`claude -p --resume <uuid> --output-format json` per utterance, with nothing spoken until
the whole answer was back (V12-2 scoped V12 to pinned turns). `[voice] harbor_kept_alive`
in the install's `config.toml` (default **false**, set **true** on the owner's install since 2026-09-24, carried to the gateway as
`HARBOR_VOICE_HARBOR_KEPT_ALIVE` by `keel voice install`, read as
`config.HARBOR_KEPT_ALIVE`) gives Harbor the house's shape, in
`voice/harbor_voice/harborlive.py`. **With the flag off nothing changes**: `harbormsg.send`
runs `run_turn` exactly as before and `harborlive` is never imported.

With it on, `harbormsg.kept_alive_turn` runs the turn, still inside Lane C's
`conversation_turn` lock (C-8) and still on the uuid `open_session` hands out, so V10's
rotation (40 turns or 24 hours, with the handover line) is unchanged: a uuid that is not
the held process's closes it and opens the new one. One `claude -p --session-id|--resume
<uuid> --input-format stream-json --output-format stream-json --verbose
--include-partial-messages --permission-mode auto --model <converse>` runs under the
talker's config dir and working directory; each sentence goes down its stdin, the text
deltas are cut by `Cutter` in `keel/sentences.py` and each finished part is left in the progress
inbox marked `part: true` (`leave_part` in `keel/narration.py`, V12-5), where the watch loop
speaks it at once in Harbor's voice (`Turn.streams`). A ```board block is drawn as it
closes through the talker's `BoardPen`, nothing after a block that reported is spoken
(N7, C-18), and the final `said` and `written` come from the same pen
(`drawing.read_answer(pen=...)`), so no block is pushed twice. A part never carries the
connect directive. A tool call ends the message it closes (lane H, H1): the cutter is
flushed so a one-line preamble ("Let me check the board.") is its own part rather than
running into the answer's first sentence, and the answer handed back starts with the
preamble, because `result` carries only the last message and the user heard both. The final
answer still lands in the say inbox; the dispatcher compares
what was spoken with it (V13-G7): covered finishes silently, a prefix speaks the
remainder, a cut stream speaks it whole. A streamed answer that has started is never given
up on out loud. A streamed turn that HAS given up (nothing was spoken by the mark) keeps
the c-221 promise: a part arriving after "I'll answer in text instead" is refused, the
streaming is latched cut, and the answer is filed (review item 4).

**Another process's turn.** A typed ask runs its own `-p --resume` on the same session, and
a process holding the conversation in memory would fork the history. The held process
remembers the session record's turn count after its own turn; when the count has moved
(someone else answered, `count_turn`), it is closed and the next turn resumes from the
transcript. A turn that another process took without counting it (it failed part way) is
not detected; that is a residual risk, not a designed case.

**When it fails** (V12-3). A process that will not open, or dies before any part was left,
is closed and the turn runs one-shot with what is left of the one deadline (review F3). A
process that dies after a part was left is not asked again; the turn ends on
`harborlive.BROKE_OFF`. An overrun kills the group and raises as the one-shot does. An
idle process is closed after `HARBOR_VOICE_HARBOR_LIVE_IDLE` (600 s). A process is stamped used
under the lock as it is handed to a turn, so the janitor cannot close it under one, and
with the flag on the gateway's `serve` installs `harborlive.install_shutdown`: an exit or
the service manager's SIGTERM drops the process first, since its own process group would
otherwise outlive the gateway (review item 5). The proof is
`harbor_kept_alive_section` in `bin/keel-voice-selftest`, against a fake streaming
`claude`; nothing has been run against a real one yet.

## The board half and the machine half of a house turn (V12 slice 2)

Built 2026-09-21. Slice 1's split is what made a turn two halves joined by a plain
transport: the machine half takes a plain `plan` dict and yields plain JSON-able events, and
the board half talks to it through the `/api/house/` routes on this machine's own `keel
serve`, on loopback.

**One turn, and where each part of it happens.**

| | The board half (`keel/converse.py`) | The machine half (`keel/housetier.py`, `keel/housetalk.py`) |
|---|---|---|
| the refusals that are settings | archived, no session | |
| `--connect` | the hold goes on the card first, with no `stopped` yet | `open`: is the house busy, is there memory, stop its background session, start the `claude` |
| | writes what `open` reported into the hold, notes the card | |
| each sentence | `say` with the card, the user's words and the turn id | the framing, the process, the cutter; parts stream back as they are written |
| the record | the exchange note, the clip, the hold refreshed | |
| "back to Harbor" | `close` with `wake: true` when the hold says `stopped` | the conversation ends, and then `house.wake` runs |
| | the release note, from whether it woke | |

**Each fact is decided by the half that can see it.** Whether a house is busy and whether
there is memory for another `claude` are facts about the machine, so they live in `open` and
come back as a CODE (`busy`, `memory`) that the board half turns into one of its own spoken
sentences: the words stay where the card's name is, and a machine is spoken as "This
machine" (`converse.THIS_MACHINE`). Stopping the house happens in `open`, which answers
whether there was one to stop, and that is what the hold records and what decides at the end
whether the house is woken or left as it was found.

**The key in the header.** `X-Keel-House` carries this machine's own key
(`<state>/house.key`, 0600, minted once), the one `keel converse` on this machine presents to
127.0.0.1. A request carrying it with `X-Forwarded-*` or a `Tailscale-` header is refused,
because that caller has no legitimate hop. The shared house key
(`~/.config/keel/credentials/house-key`, 0600; `keel house key` says whether it is there and
`keel house key mint` writes one, and neither ever prints it) is no key to these routes. It
still exists because Bosun's key is derived from it (`keel/authority.py`), and `shipyard
init` mints it. The other three rules above are unchanged.

**Every path that ends a hold on a house ends it here.** "Back to Harbor" and the hold
running out end it, and so do the deck's Stop, its Resume, a gate answered and Open in
Claude app: each of them (`actions.end_conversation`) closes the conversation through the
house tier and clears the hold before it goes on. Otherwise the user's tap would be quietly dropped
by the drain that was meant to carry it, and a resume is refused while a headless `claude`
still holds the session, so a Resume tapped mid-conversation would fail for a reason
nothing on the page could explain. A close that fails writes a note on the card, and the
drain's next pass puts the house back.

**The hold going while `open` is in flight.** The hold has to be taken BEFORE the round trip,
because the routes refuse a card the board does not say is held by voice, and what the
machine half answers (whether it was the one that stopped the house) can only be written into
that hold afterwards. The user can stop the house from the deck, or answer its gate, inside that
window, and both clear the hold on purpose. So `converse.opened` checks that the hold is the
SAME one it took, by its `at` stamp (`until` moves on every sentence, so it says nothing about
which hold this is), and when it is not, it undoes what this open did: the conversation is
closed and the house is woken if this open is what stopped it. The user hears "That house was
stopped, so we are back to Harbor." Without the check a hold the user had just ended came back, and
the drain stayed away from a house nobody was talking to until it ran out.

**When the house's stop fails** (r-17, c-539). `claude stop` can answer that it could not
confirm the stop because its background service may be restarting, and asks to be tried again
in a moment. `harness.stop` does exactly that once, after `harness.STOP_RETRY_PAUSE` (two
seconds), and only on that answer (`harness.STOP_RESTARTING`); any other failure raises with
the harness's words on one line. The same answer twice is settled by the listing (r-25,
c-557): a harness can say it twice for a session that has stopped, leaving the user
to connect from a terminal. So `harness.stop` asks `claude agents --json` under that
config dir, up to `STOP_LOOKS` (5) times `STOP_LOOK_PAUSE` (2s) apart, because a stopped row
lingers a few seconds. Not listed is stopped: the stop returns and the connect carries on.
Still listed, or a listing that never answers, raises one plain line: "the house's session
<id> is still running and would not stop; run `CLAUDE_CONFIG_DIR=<dir> claude stop <id>` and
connect again" (the config dir named, since the bare command under the user's default dir cannot
see the session). Every caller of `harness.stop` gets the same reading. `open` answers that as
`refused` with the line as its reason and drops the kept plan, the board half gives the hold
back, and the user hears "This machine would not open that conversation: claude stop ... exited 1:
...". It used to be a 500 (the stop sat outside `open`'s try). A house stopped by
`converse.take_hold` fails the same way (`converse.stop_refusal`), with no hold written and
the user's question left on the card.

**When `keel serve` does not answer.** Connection refused, a name that does not resolve, or
three seconds with no connection (`housetier.CONNECT_TIMEOUT`: its own much shorter wait inside
the nested three, because connecting is not thinking). That is `housetier.Unreachable`, an
`Away`, and nothing can have reached a `claude` through a connection that was never made, so a
pinned turn falls back to the V4 one-shot (`claude -p --resume` in the caller's own process,
with the plan built there) and the card says so. Once part of an answer has been spoken
there is no fallback, for the reason above: the user would hear two answers.

**The plan is kept for the life of the hold.** Opening the board once per request puts a
board read in front of every sentence. The plan is cached per card in the serving process
(`housetier.Plans`) and dropped on the close, on the hold's own expiry, and when the card's
session id moves under the live conversation. A conversation that is STARTING always asks, so
the board's two questions stay in front of every conversation and the cache is a latency fix
rather than a way past them.

**And the stream must not be buffered.** `say` goes out with no content length, a flush per
line, `Cache-Control: no-store` and `X-Accel-Buffering: no`. A proxy that held the stream
would deliver every part with the result and give back the five second silence this
requirement removed, so `tests/test_housetier.py` drives the real client and fails a client
that buffers.

**Egress.** The house's answer stays on this machine as text until the speech engine
speaks it, and the clip is noted on the card, exactly as for a personal house. No credential
moves.

## Harbor enters and leaves a house (V8 heard; V13's persona)

The question V4 leaves open is "who am I talking to right now", and on a phone in a pocket
the only honest answer is one the user can hear. V8 answered it with a second VOICE; V13 answers
it with a MOVE: Harbor enters and leaves a house, so the one Harbor voice is kept. Asked to
enter a house, Harbor enters, the house answers, and it sounds as if Harbor is the one
speaking; it leaves the same way.

So a switch in either direction is spoken, by code, in the ONE voice there is, and what it
says is where Harbor now is. Nothing here costs a model turn, and none of it can be wrong,
because the gateway is the thing that took the pin.

| When | Words | Where the audio is from |
| --- | --- | --- |
| The verb matched, at once | "Connecting you now." | a rendered clip |
| The house is the user's | "Entering card 272, Voice slice 5." | synthesised at connect |
| The connect passes four seconds | "Still connecting." | a rendered clip, said once |
| The user asks to leave | "Leaving card 272. Back with you." | synthesised at release |
| The hold runs out while the user is quiet | "Leaving that house. Back with you." | a rendered clip |
| The switch could not happen | "I cannot enter card 419: it is building right now." | synthesised, no tone |

**One voice, and `turn.speaker` is the record rather than the chooser.** V8 had four lines
in two voices, and the rule was that the voice followed whose answer it was:
`Dispatcher._ask_house` sets `turn.speaker` from the RESULT, so a refusal was Harbor's even
mid-conversation because the house did not say it. That line is unchanged and so is
everything that depends on it: the page's header and the transcript still say which house
said a thing. What changed is the last step, `config.voice_speaker`, which answers Harbor
for every role. There are several refusal paths (mid-work, no house, an archived card,
short of memory, a relaunch that failed, a hold taken away) and all of them
are covered by that one line rather than by each of them remembering. V8's list of refusals
also names "the name matched two cards", and that one has no trigger: the verb is an opening
plus an ID (`verbs.card_id_in`), never a name, so two cards cannot match. A sentence that
parses no id connects to nothing and is an ordinary question to Harbor.

**The words the user uses to go in and to come out.** V4's table gained "enter", "go into", "step
into" and "take me into", and the release table gained "leave", "exit", "come back" and
"step out", because those are what a person reaches for once the thing that moves is Harbor.
The rule around them is untouched, which is what makes a word as short as "enter" safe: an
exact opening plus something that reads as a card id, never the model, so "enter 272 into
the form" connects to nothing and "go into more detail" is an ordinary question. Connecting
by description (V11) is untouched too.

**A refusal says which act it refused.** `keel converse --connect` owns every reason a
switch cannot happen and answers in its own sentence; what those sentences never said is
WHICH act was refused, so "c-419 is building right now" arrived after "Connecting you now"
and left the user working out which side of the switch the user was on. `verbs.cannot_enter` frames the
verb's reason with the act ("I cannot enter card 419: it is building right now"), turns a
leading card id into "it" so it is not named twice in one breath, and says every other id
in it the way `verbs.say_card` does. The reason's own words and capitalisation are copied,
because rewriting what the verb chose is how a copy starts disagreeing with it.

**Line 1 names no card, and that is a departure from V8's own wording.** The text there
reads "Connecting you to c-272", and a line with a card id in it cannot be pre-rendered,
because `bin/keel-voice-corpus render` runs long before anybody knows which card. Line 1's
whole job is to land AT ONCE over a wait that is about to happen, and a live synthesis is
the one thing that cannot promise that. Line 2 names the card two seconds later and the
header names it immediately. That Harbor says "connecting" in its own voice is the user's
decision.

**How a card id is SAID.** `verbs.say_card` turns `c-272` into "card 272", which is also how
the user says it out loud. MEASURED, 2026-09-20, by synthesising each and comparing lengths:
inside a carrier sentence Chirp 3 HD reads "c-272" in about 2.7 s, which is where "c dash two
seven two" and "c minus two seven two" land and nowhere near "c two seventy two" (2.4 s). The
hyphen is spoken one way or the other, and neither reading is a thing a person says.

**The title is cut in code, never by a model.** `verbs.short_title` cuts at the first colon,
comma, bracket or spaced hyphen, caps at six words and drops a word left dangling, so
"Voice slice 6: the heard handoff and the house voice (V8)" is said as "Voice slice 6". The
page's header keeps the whole title; only the spoken line is cut. Naming the card at all is
allowed by the egress split because the user asked for that card, which makes it a direct answer;
the expiry line is unprompted and names nothing, which `corpus.LEFT_HOUSE` does by
construction rather than by a rule somebody has to apply.

**The tone under the words.** `speech.tone_pcm` is ONE note, about 100 ms, the same going in
and coming back, sent down the same audio channel as speech (`Gateway._send_tone`). It was
two, rising into a house and falling back to Harbor, and V13 took the direction out: a
direction is only worth hearing while the two sides sound different, and with one voice the
LINE is what says which way it went. It is arithmetic with no synthesiser behind it, so it
cannot fail the way a spoken line can, and it still says a switch happened when the words are
lost to a bad connection. It lands in front of the line it introduces, never in front of one
already being said. A REFUSAL PLAYS NO TONE, because the tone means the switch happened. On
the browser floor the page delays its own utterance until the queued tone has finished
(`speakHere`), which is the one place the two are different players rather than one stream
of samples.

**A silent unpin never happens.** The pin is dropped lazily, inside `Dispatcher.pinned`, so
a conversation the user walks away from would end with the header clearing at the user's next utterance
and nothing having said so. `Dispatcher.pin_changed` is injected by the gateway the way
`deliver` and `speak` are, and `Gateway.pin_moved` keeps one timer against the hold's own
expiry. The timer FIRING is itself the answer: every other way a pin can end cancels it, so
a timer that survives means the hold ran out, and the check for "is there still a pin" that
would seem natural here is exactly the check that would say nothing at the one moment this
exists to speak. It says the leaving line that names nothing, with the tone, and leaves the
release to the drain, which owns an expired hold. It is
process state, and a restart forgets it: the board's hold expires on its own clock either
way, so the worst case is a missing sentence and never a stuck house.

**Seen as well as heard.** The header takes the house's colour for as long as the pin holds,
and a house's colour is its card's SPACE: `keel converse --connect` returns it, the page puts
it on `body[data-house]`, and `app.css` colours the card's id (in the header's who chip
and the voice bar's chip) and the hold's ring in that space's accent. The deck has exactly
two palettes and they already mean something, so a work card reads teal from a personal
page. It is scoped to the card's own id because the bar and the transcript are about what
the MACHINE is doing, which does not change with who is on the other end.

**The way back is the gateway's, and the house may ASK for it.** Unchanged from V4 in the
part that matters: the leaving words are matched in the gateway before anything is routed,
so a house cannot mishear its way into keeping the user, and the tap on the header pill is the
same path. A house asked to leave is not stuck
saying "I can't end my own session, tap Stop on the deck": it says goodbye and ends its
answer with a directive, and the GATEWAY leaves. Both nets are below, under "Leaving in the user's
own words".

**The words are read leniently now, and only while the user is pinned.** `verbs.leave_intent` is
the exact table plus the wrappers a person really puts round a request, and `Gateway.on_text`
asks it where it asked the table, so a leave still costs no turn and no judge ever sees it.
One consequence is deliberate: while the user is PINNED, "that's all" comes out of the house
rather than closing the conversation, because coming out is the narrower act and saying it
again closes it.

## Re-arming after a switch, and a socket you can read back (V13)

The case it answers: a
connect finishes (`connect-taking` on the transcript), the page shows
"listening" for a minute, and not one frame of audio reaches the gateway before the user
gives up and presses the orb by hand. Two things were missing and they are
different kinds of missing.

**Nothing re-armed a microphone after a switch.** `Gateway.turn_over` is the only thing that
reopens one, and it fires when a TURN ends; a connect is not a turn. So the gateway now sends
`{"type": "listen-now", "reason": "connected"|"released", "generation": n}` once, after the
switch has FINISHED SPEAKING. `say_line` returns when the audio has been streamed, so the
ordering is the mechanism: the page is never invited to open a microphone into the tail of
the gateway's own voice. It is an invitation and not a command, exactly as `listen` is: the
page knows whether it is paused, whether it is already holding and whether a microphone will
open at all, and it drops this on the floor in all three cases. A REFUSED connect sends
nothing, because nothing was entered.

**Only for a switch THE USER ASKED FOR, and the expiry is the exception.** A phrase and a tap on
the header both count; a hold that RUNS OUT does not. It runs out precisely because the user said
nothing for the whole of it, so the user has walked away, and a microphone opened then is a
microphone in the user's pocket. The page's own quiet cap would close it a minute later, which is
why this is not a disaster and is not a reason to open it either.

**And nothing anywhere wrote down enough to say which half had failed.** A minute of
"listening" with no audio behind it is empty on the transcript, so afterwards there was no way to tell a page that never
opened a microphone from one that opened a microphone which heard nothing from one whose
frames never crossed the socket. `Dispatcher.log_event` is the record, written against the
turn in flight if there is one and against no turn at all if there is not (a socket event
usually happens between turns, and naming the last finished turn would file a listen under
the question before it). Four kinds:

| Kind | When | What is on it |
| --- | --- | --- |
| `listen` | a `start` arrives | `handsFree`, the page's listen number, whether a conversation is open |
| `frames` | the FIRST binary frame of that listen | the listen number |
| `endpoint` | the gateway ends a listen | `hangover` or `quiet` |
| `listen-now` | the gateway invites a press | `connected` or `released` |

The useful shape of it is an ABSENCE: a `listen` with no `frames` after it is a microphone
that received nothing, which is exactly that silent minute, visible instead of inferred.
`frames` is written ONCE per listen rather than once per chunk, because a line every 32 ms
would answer the question by drowning it.

**The page's own watchdog reports in, and the gateway never acts on it.** The page can see
things this end cannot: that it armed, that a press happened, that playback ended, that five
seconds went by with no frames leaving it. It sends
`{"type": "trace", "event": "arm"|"press"|"frames"|"playback-end"|"quiet"|"stalled"|
"release"|"repress", "reason": <free text>, "listen": <listen id>, "at": <ms since page
load>}`, and the gateway writes it to the transcript as `kind: "page"` and does NOTHING
else. That is the whole of its safety and it is not a stylistic preference: this socket is
the only write path into the agent, it is fenced by origin alone, and a diagnostic message
that could arm a microphone, move a pin or start a turn would be a second way in on the
dashboard's own origin. Four fields, copied and capped, and no branch anywhere reads them
back.

## Connecting by description: the model picks, the gateway pins (V11)

Built 2026-09-20 (card c-419). A user often does not know a house's number
and relies on the model to find it. The phrase table above parses an id and
nothing else, so "connect me to the house doing the voice thing" is an ordinary question
to Harbor, and Harbor cannot pin: only the gateway runs `keel converse`.

**The model names a card. It never connects.** The sentence goes to Harbor exactly as it
did, carrying the deck digest every voice turn already carries (both spaces, every card's
id, title and stage), so the routing is a read of something the turn already holds. Harbor
answers in one short sentence naming the card, and ends the answer with a directive that
`verbs.connect_directive` reads in code. The gateway then calls `Gateway.connect_by_model`,
which is `connect_to` with `spoken=True`: the same guards, the same refusals, the same four
spoken moments. There is no second connect path and nothing about the first one changed.

**The directive, and why it carries a key.**

```
<<keel-connect c-317 9f4c2a>>
```

`Dispatcher._ask_harbor` mints six hex characters per Harbor turn
(`verbs.connect_key`), puts them in that turn's framing (`harbormsg.CONNECT_NOTE`, which
also carries the example sentence and the rule that Harbor does not say "connecting"), and
keeps them on the turn. Only a directive carrying THAT turn's key may pin. A fixed sentinel
on its own is producible by accident in the one case that matters, which is an answer that
QUOTES the form, and "how does the connect work" is a question the user can ask out loud; a key
the user never said, that is not in the digest and is not in any earlier answer, cannot be
guessed or replayed. A mistyped key is a MISS: the user hears the sentence, nothing pins, and the user
can say the id.

**Stripped by shape, pinned by shape and place and key.** Anything of the directive's shape
is removed from what is spoken wherever it sits, because the token read aloud is gibberish
however it got there. Only a well-formed directive at the very END of the answer, with this
turn's key, may pin.

**"Alone on the last line" is what Harbor is told; "at the very end" is what is checked.**
The answer never reaches the parser with its newlines: `harbormsg.SayInbox.write` flattens
every line into the inbox (`" ".join(text.split())`), which is that channel's rule and is
shared with `progress` and `opening`. So a check about lines would be a check about
something the gateway cannot see. The instruction stays the line, because a directive
written on its own line IS a directive at the end once the inbox has flattened it.

**The five conditions, and four of them hold by construction.**

| Condition | How it holds |
| --- | --- |
| The answer is Harbor's, never a house's | Only a Harbor turn is given a key, and an empty key matches nothing |
| It is this turn's key | `verbs.connect_directive` compares it |
| It ends the answer | The same function, and nothing after it, not even a full stop |
| The answer was actually SPOKEN | Only the branch that speaks calls `Dispatcher._take_connect`; held, gave-up and not-live all call `_drop_connect` instead |
| Nothing is pinned right now | `_take_connect` asks, because a LATE answer from before a pin must not take the microphone off the house the user is talking to |

Every drop is a `connect-dropped` line in the transcript with its reason, and a directive
that was read is a `connect-directive` line, because a pin nobody can explain afterwards is
the thing this record exists to prevent.

**What is refused is refused by the verb, in its own words.** A card that is building, an
archived card, a card with no house session, a machine short of memory, and a card the model named that the board does not have ("I could not find a card called
c-404", which is reachable here in a way it is not from the phrase, because a digest is a
moment old). Each is Harbor's voice, no tone, and no pin.

**The judge is offered the place and decides nothing.** `preturn`'s `route` menu gains
`connect` while the user is NOT pinned, the way it gains `connected` while the user is
(`dispatcher.CONNECT_CRITERIA`, `CONNECTED_CRITERIA`, passed through `judges.ask`'s
`criteria`). It is shadow like every other judge, no path in `server.on_text` reads a
`connect` verdict, and `rule_route` deliberately does not answer it: the rule is what the
turn actually does, and what it does is ask Harbor. A classifier that knows a connect
request when it hears one still could not say WHICH house, which is the whole of why this
requirement is the model's and not a judge's.

**Harbor is taught in two places and they are not the same kind of thing.** The per-turn
framing is the mechanism, because it is the only place the key can ride and because it
arrives with the thing it governs. `<install>/memory/talker/voice-turn-shape.md` and
`<install>/memory/talker/talking-by-voice.md` carry the standing version, including the line that
matters most to a model deciding on the user's behalf: a house does NOT need to be running to be
connected to.

## Leaving in the user's own words, and the directive that lets the house do it (2026-09-21)

The case it answers: inside a house the user says
"Okay, you can exit the pouse now" (speech recognition hears "pouse") and then "You can go
back". `verbs.is_disconnect` matches the WHOLE utterance against a fixed table, so both go
to the house as questions; the house answers "I can't end my own session, tap Stop on the
deck", which is true, and the user has to tap the header pill to get out. There are two nets,
and they fail in opposite directions on purpose.

**The first net: `verbs.leave_intent`, a lenient reading beside the table.** It is asked
where the table was asked, before the `preturn` seat and before anything is dispatched, so a
leave still costs no turn and no judge can move it; and the table is asked first inside it,
so this can only ever ADD. The reading is four rules, and a sentence must pass all four:

| Rule | What it stops |
| --- | --- |
| Ten words at most | "Can you exit the house once the tests are green and you have pushed it" |
| No question opener (why, how, what, when, where, which, "can you explain", "tell me") | "why did you exit the loop", "how do I go back to the previous version" |
| A leave phrase at the FRONT, once the lead-ins ("okay", "you can", "can you", "alright", "so", "please", "harbor") and a trailing "now"/"please" are off | "I went back to Harbor after lunch" |
| And nothing after it but an object: the house, the card, it, here, out, or "to" Harbor / you / the board | "leave that file alone", "go back to the first decision", "step out of the way of the drain" |

The leave phrases are the table's own words plus what a person reaches for: exit, leave, get
out, step out, come back, go back, back to Harbor, back to you, hang up, disconnect, that's
all, done here, we're done. The HOUSE WORD IS MATCHED LOOSELY (house, pouse, mouse, how's,
hows, houses) because that is what came out of speech recognition, and it is safe because it
is only ever read AFTER a leave phrase: a wrong reading of "mouse" can do nothing unless the user
also said "exit" in front of it. Every rule leans the same way because the two mistakes are
not the same size: a missed leave costs one more sentence and a tap, and a question read as
a leave ends a conversation the user was in the middle of and puts the house back to sleep.

**The second net: the house says goodbye and asks.** `prompts.SPOKEN`, the framing every
connected conversation gets on its first sentence, now says that a request to leave is
answered with one short goodbye and `<<keel-leave>>` on its own line at the end. It is the
c-419 connect directive's shape and its guards, in the other direction:

| | Connect (c-419) | Leave (2026-09-21) |
| --- | --- | --- |
| Who writes it | Harbor, on an ordinary turn | The house, inside a conversation |
| Who reads it | The gateway (`verbs.connect_directive`) | Keel (`sentences.leave_directive`, and the cutter) |
| Keyed | Yes, six hex characters minted per turn | No: only the house the user is already in can write one |
| Stripped | By shape, wherever it sits | The same |
| Acted on | Only at the very end of the answer, with this turn's key | Only at the very end of the answer |
| When | After the answer has been SPOKEN | The same |

**Why the leave needs no key and the connect does.** The connect moves the user into a house the user
did not name, so a token produced by accident (an answer that QUOTES the form, which is a
thing the user can ask about out loud) costs a house the user never asked for. A stray leave ends a
conversation the user reopens with one sentence. So the shape is stripped either way, and only the
connect is keyed; the leave's guard is that it must END the answer, which is what makes
"you would end with `<<keel-leave>>` and I would read it there" an ordinary sentence.

**It is read twice and means one thing.** On a streamed turn `sentences.Cutter` holds it
back as it arrives, exactly as it holds a fence, and emits `{"type": "leave"}`: without that
the token would be SPOKEN, since a part is said the moment it is finished. The finished
answer carries it too (the answer is the whole answer), and `converse.LeaveDirective.take`
reads it there, which is the only reading a one-shot turn gets (the phone Harbor's single
question, a turn typed into the ask box). A boolean cannot be set twice, so the second
reading is free. `keel converse` then returns `leave: true` beside the sentence and RELEASES
NOTHING: one way out, and it is the gateway's. An answer that was ONLY the token has nothing
left in it once the token is out, so a fixed sentence stands in ("Right, I'll let you go.",
`converse.LEAVING_SAID`), the way `connect_bare` does at the other door: without it the user would
hear the gateway's "that did not come back" and then be taken out of the house.

**The gateway leaves the way it always does.** `Dispatcher._house_landed` records
`turn.leave` from the verb's result, beside the hold, and `_take_leave` runs after
`_house_answer` has spoken the goodbye: `Gateway.leave_by_house` is `disconnect(spoken=True)`,
the same call the phrase and the tap on the header make, so the release, the one leaving
line naming the card, the tone and the `listen-now` are the ones that already exist. It acts
only if `turn.spoken` says the goodbye was actually voiced and only if the user is still in that
card's house; otherwise it is a `leave-dropped` line in the transcript with its reason, and
the hold expiring is the repair. `leave-directive` and `leave-taking` are the other two
lines, because a conversation that ended for no visible reason is the thing this record
exists to prevent.

## Narrating a connected turn from real activity (V5)

Being built 2026-09-20 (card c-317, requirement V5 in `<install>/history/docs/voice-next.md`). A connected
turn with edits can take a minute, well past the gateway's give-up mark, and until this
slice it was a silent block: `_ask_house` was the one answering path that never entered
`Dispatcher._watch`, so the filler, the narration and the give-up clock all sat idle
through the longest turns the gateway takes.

**The stream was already there and nothing used it.** A connected turn is a headless `-p`
turn, so it can run as `--output-format stream-json --verbose` and every tool the house
picks up arrives as a JSON record while it is still working. Probed on the Linux host on
2026-09-20 against Claude Code 2.1.278 (`state/cards/c-317/probe/`): the records arrive
INCREMENTALLY, about one tool call every two seconds, not held back to the end; a `-p
--resume` turn streams the same way; and the LAST record is the same
`{"result": ...}` payload `--output-format json` already returns, so `harness.turn_answer`
reads a streamed turn unchanged. It costs no extra tokens, because these are the tokens the
turn was already spending.

**The vocabulary is a closed set, and that is the whole egress argument.**
`keel/narration.py` maps a tool call to an ACTION key (`edit`, `read`, `search`, `test`,
`version_control`, `card`, `fan_out`, `look_up`, `run`) and each key to exactly one
sentence: "Still on it, editing a file." Nothing read out of a tool's input can reach the
sentence, so a file path, a card id, a branch name or a secret on a command line cannot be
spoken even by accident, and cannot be written into the voice segment's data directory to be
spoken later. The gateway's `filler.progress_guard` is the second line; the closed set is
the first, and it holds by construction rather than by screening.

| what it sees | what it says |
|---|---|
| `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | Still on it, editing a file. |
| `Read` | Still on it, reading the code. |
| `Glob`, `Grep` | Still on it, looking through the code. |
| `Bash` with `make`, `pytest`, `tox` | Still on it, running the tests. |
| `Bash` with `git` | Still on it, working through git. |
| `Bash` with `kb`, `keel` | Still on it, updating the card. |
| `Bash` with anything else | Still on it, running something. |
| `Task` | Still on it, handing part of it out. |
| `WebFetch`, `WebSearch` | Still on it, looking something up. |
| any other tool | nothing at all |

A tool that is not on that list says NOTHING rather than something vague: silence beats a
wrong word, and "still on it" about something we could not name is worth less than the four
seconds of quiet it replaces. Bash is the exception and goes the other way, because a shell
command is always some work being done: the verb allowlist names it, or `run` does. Only
the command's first meaningful verb is ever read, and `cd <somewhere> && make test` is
narrated as the tests, because that is the shape a house actually writes.

**A subagent's tools are not the house's own.** A record carrying `parent_tool_use_id` came
from something the house handed out, and the house's own `Task` call already said so.
Narrating the fan-out's reads would be narrating one action twice at two depths.

**Never the same line twice in a row, and it is the ACTION that is compared.** V5 asks for
"never the same progress line twice in a row" and "nothing when nothing changed", and there
is no duplicate check on the progress channel otherwise. Two reads running render the same
string, so comparing strings would catch that pair by accident and miss the pair where one
template is later reworded; `narration.same_action` compares the key. The rule is enforced
on Keel's side as well as at the gateway, because the inbox keeps only the freshest record
per silence window, and a run of duplicates would push the one line that differed out of it.

**Where the line lands.** The progress inbox (`harbormsg.PROGRESS_DIR`), which has had the
silence gate, the per-turn budget and the shape guard since the pane era and which nothing
has fed since the Harbor tier stopped writing to it. A line in the SAY inbox ENDS the turn
that reads it; the progress inbox narrates without ending, and that distinction is the
reason there are two directories. The record is the shape `SayInbox` reads (`text`, `at`,
`turn`) with `action` and `tool` beside them, so the gateway can tell a house activity line
from a `bin/keel-voice progress` one and can ask the `narrate` judge about the action.
Keel never imports `harbor_voice`: the gateway passes the directory to `keel converse`,
because the segment's layout is the gateway's to know and the two run on different
interpreters.

**The connected turn is a WATCHED turn now, and it used to be a silent block.**
`_ask_house` was the one answering path that never entered `Dispatcher._watch`, so through
the longest turns the gateway takes (a minute or more when the house edits something) the
filler, the narration, the give-up clock and the abandon all sat idle. The verb now runs on
a worker thread that writes its answer into the SAY inbox stamped with the turn id, exactly
as `harbormsg`'s Harbor worker already does, and `_ask_house` hands off to `_watch` exactly
as `_ask_harbor` does. Everything that machinery knows how to do then works on a connected
turn with no second copy of it. What the verb sends back BESIDE the sentence (the hold's
new expiry, an `unpin`) is stashed on the turn and acted on by the watching thread, never
by the worker: the pin is read by the socket handler and by the next turn, and moving it
from a thread that is about to be thrown away is how two turns disagree about which card
they are in.

**What the user hears, in order.** V5 asks for three things and they arrive in this order:

1. **Nothing at all, if the answer starts inside four seconds**, and that is the 2026-09-21
   change. V5's first line was `corpus.HOUSE_OPENER` ("Heard you, passing that to the house
   now."), a pre-rendered clip spoken at the top of every connected turn, and it was cover
   for a COLD PROCESS: back then a turn's first second went on stopping one `claude` and
   starting another. V12 opens the conversation at the connect, so the first spoken part
   lands in about three seconds, and V13 made Harbor ENTER the house rather than pass
   anything to it: the line was wrong about where the user was and it talked over a wait that was
   usually already over. It is deleted, clip and all.
2. **A filler line, and only into a real silence.** A connected wait is covered exactly as
   a Harbor wait is: the ordinary corpus, through the same `self.filler.line(turn.said,
   self.snapshot.doc)` call, started on its own thread in `_ask_house` while the verb is
   handed off, and spoken by `_watch` only once nothing has been said for
   `config.PROGRESS_SILENCE_AT`. There is no second filler mechanism and no second gate. A
   line that is not written by the time the gate opens is dropped rather than waited for,
   which is `_ask_harbor`'s own rule for a filler that misses its budget (two seconds,
   against a four second gate), and a REAL progress line is preferred over a canned one, so
   a house that picked up a tool inside the gate is narrated instead.
3. **The house's real activity**, from the stream, through the progress inbox.
4. **The house's own one to three sentences**, the answer, spoken as it is written (V12).

**A part does not cut a filler mid-word, and that is a decision.** The only thing that stops
audio in flight is the generation counter: `_say` and `Gateway.speak` check it per chunk,
and it belongs to THE USER (`Dispatcher.cut`, which is barge-in). Bumping it for a part would
drop the part's own audio along with the filler's, because the part is spoken under the same
turn, and the page would read it as an interruption the user did not make. `_say` blocks for the
length of the audio and the watch loop is the only thread claiming the inbox, so a part that
lands under a filler is spoken the moment its words end; the cost is bounded by one short
rendered line, and the alternative risks the answer itself. What IS enforced is that a
filler is never STARTED once the answer has begun: the same `turn.answering` latch that ends
a turn's narration also holds the opening filler and the twenty second hold repeat.

And everything before the answer is in HARBOR's voice while the answer is in the HOUSE's
(V8, above), which falls out of the order rather than being decided anywhere: a turn starts
as Harbor's and only the ANSWER moves it (`_house_landed`), so the filler, every progress
line and the give-up line are Harbor's for free.

**The give-up, and the one place a connected turn differs.** At the give-up mark an
ordinary turn promises TEXT, and that promise is binding: the answer goes to a card and is
never spoken. A connected turn cannot make that promise, because the answer is ALREADY
going to the card the user is talking to (`converse.record` writes the exchange with the user's words
verbatim), so a second card would be a duplicate record filed against a different card. It
promises the answer instead ("The house is still going. I'll tell you when it answers.")
and holds it. When the answer lands, `_house_answer` asks three questions in order:

- **Is the user there at all?** No, and it is not spoken: `_finish_silent`, and the card has it.
- **Is the user mid-sentence?** A DELAYED ANSWER NEVER INTERRUPTS THE USER. It waits for that turn to
  end and then speaks, once. "Is a turn over" is the same question `refine` asks, asked the
  same way. Past `LATE_ANSWER_WAIT` (two minutes) the user is treated as gone.

**A SUPERSEDED HOUSE TURN IS HELD, and this is what makes any of the above reachable.**
`Dispatcher.begin` marks the turn it supersedes `held`, and `held` is what keeps `_watch`'s
loop alive once the generation has moved. Until c-317's send-back it did that only for a
HARBOR turn, so a superseded connected turn left the loop on the next 0.4 second tick, and
its answer sat in the say inbox until the next `begin()` drained it as `dropped`: never
spoken, never noted, and the `held_until` and `unpin` the verb asked for went with it.
That was a corner while `_ask_house` blocked and came back answered. It is the COMMON CASE
now that it is asynchronous, because a house turn that edits something takes a minute and
the ordinary shape of a conversation is that the user says something else first.

The two tiers then part company at the claim, and the difference is the point: a held
HARBOR answer is kept to be READ ("Harbor answered while you were talking"), because the user
re-asked the question and the old answer is usually stale. A held HOUSE answer is kept to
be SPOKEN, because it is a minute of that house's work on a question the user has not re-asked
and could not re-ask without waiting all over again. `_house_landed` runs first either way,
so `held_until` and `unpin` are applied whether or not anything is ever said.
- **Has it been a while?** Past the give-up mark, minutes and another question may have
  passed, so the answer opens with one preface line naming the card ("About c-272.") and
  then answers. It names the card because the user asked about that card, which is the egress
  split's "a direct answer may name what the user asked about". A turn that came back promptly
  gets no preface, because then it is obvious what it is about.

**Abandoned mid tool-call is said out loud, once.** An ordinary abandoned turn is silent
because Harbor's answer may still arrive and be filed; a connected turn's `keel converse`
has by then been killed with its process group and nothing is still coming, so silence
would leave the user waiting on a turn that has ended. One line ("That did not come back. It is
on the card."), and `converse.record_stopped` has written the user's question, why the turn
stopped, and how far it had got, in action words and never a path.

**The turn keeps its process group.** `harness.turn_streamed` is `run_alone` with a reader
on the pipe: same `start_new_session`, same `kill_group` on the timeout (SIGTERM, two
seconds, SIGKILL), the readers joined before it returns. Two pipes need two readers, so
stderr gets one of its own; `communicate` exists because a process that fills a pipe nobody
is draining blocks forever, and reading stdout by hand puts stderr in exactly that position.
A listener that raises is swallowed and the turn carries on: a narration that failed is a
quieter wait, never a lost answer.

## The `narrate` seat (V5 beside V10)

The judge V10 named for "per house activity event in V5: say it, or let it pass". Built
2026-09-20 with V5 (c-317); the key, the switch, the log and the report were already there
from c-313, so this slice added the SEAT and nothing else about the switch moved.

**Where it sits.** `Dispatcher._narrate_seat`, at the progress claim inside `_watch`, and
only for a line carrying an `action` (a house activity line). A `bin/keel-voice progress`
line from anywhere else is untouched: this slice narrates a house, it does not change the
channel anyone else writes to.

**THE RULE, which is the baseline the shadow log is scored against.** Say a house activity
line when ALL of these hold, and let it pass otherwise:

1. it is the freshest unclaimed line for this turn (the inbox drops the older ones in the
   same window, because a progress line is a snapshot and not a backlog);
2. at least `PROGRESS_SILENCE_AT` (four seconds) has passed since anything was spoken in
   this turn;
3. its ACTION differs from the action of the line last spoken in this turn;
4. the give-up line has not fired;
5. the turn's progress budget (`PROGRESS_REPEAT_LIMIT`, twenty) is not spent;
6. `filler.progress_guard` clears its shape.

Rule 3 is the new one and it is V5's "never the same progress line twice in a row" and
"nothing when nothing changed". All six are worked out BEFORE anything is said, into one
reason, so the rule verdict the seat logs IS the decision the loop is about to make. Asking
the judge inside one branch and not the others would log a rule that agreed with itself by
construction, and the report's agreement column would measure the copy instead of the
decision. It is the same reason `rule_route` lives on the dispatcher.

**What is sent is an action key**, out of `keel/narration.py`'s closed set: the judge is
asked whether an edit is worth mentioning, not what was edited, and the second question's
answer is the one thing that must never leave the machine. The seat returns whether it ASKED
and never what to say; the verdict is read the way the `preturn` seat reads its own
(`ruling.by(...) == "jev"` before the value), and there is nowhere here for a verdict to go.

**`narrate` MUST STAY `off` OR `shadow` UNTIL ITS PER-EVENT VOLUME IS MEASURED.** The cap
throttles the SHADOW SLOT; it is not a budget for an `on`-mode await. In `shadow` a call is
fired and never waited for, so twenty candidates cost the turn nothing. In `on`, `ask`
blocks for up to the 600 ms budget EACH TIME, and it does so inside the `_watch` loop that
also drives the give-up mark and the abandon: a long connected turn can raise twenty
candidates, so the arithmetic to do before the flip is twenty awaits against a loop that is
supposed to notice sixty seconds passing. That measurement has not been made. Until it has,
this key is not one of the ones a report can flip, whatever the report says about agreement.

**The cap, and why there is one.** `judges._SHADOW_BUSY` is ONE SLOT and it is
module-global, shared by every judge. That is fine for a seat asked once per utterance and
wrong for one asked per house activity event: a chatty turn is forty tool calls and about
twenty candidates, and a seat that asked on every one would hold the slot for the whole
conversation, dropping the `preturn` call that has a turn WAITING on it. So the seat asks
about the first `NARRATE_SHADOW_CAP` (five) candidates, and stands down when
`judges.shadow_busy()` says another call is in flight. Both are LOGGED as a `capped` miss
(`judges.skipped`) rather than being silent, because a report showing five calls on a
forty-event turn would otherwise read as a quiet turn rather than a capped one. A miss is
an absence: `keel/judges.py`'s tally never counts one as an agreement or a disagreement.

## Both Harbors read the deck

Since 2026-09-18 (decisions V16 to V18) both Harbors, the phone talker and voice, may READ
anything the deck shows, in either space. The spaces boundary bites on credentials, on
where houses run, and on personal content written to a work surface. It never bit on
reading, and reading it as though it did is what broke: asked about the deck's PR Review
screen, voice said it needed the user's screen, then that the data was on the work side and it
could not reach it. The deck was serving `providers.work.reviews` on loopback at the time,
and the personal contract's "never reach for a work tool" had been read as "never read
work". Nothing technical was in the way.

**The digest is the deck.** `voice/harbor_voice/snapshot.py`'s `board_doc` reads
`http://127.0.0.1:<serve_port>/api/state` and folds it through `keel/deckdigest.py` into
the document `index.py` reduces. What rides on a turn now: both spaces' cards (id, title,
stage, blocked reason, and for a card whose pull request the shipping watcher has looked
at, `pr`: its state and counts from `options.shipping.facts`, never a comment), the
needs-you queue, the running houses, the review cards (lane RC: id, title, repo and
`derived.review`, the word the deck's Reviews list shows), the segments and their
headlines, the drain pill, and each space's topics. No provider row is read: the old
scanner's rows went with lane RC, and the pull request watcher's `prs` rows went with the
PRs page (lane RETIRE, RT-1), so a work pull request is spoken about through its card.
`bin/keel-voice-selftest`'s `deck_state()` models the same deck: review cards and a
shipping card in `cards`, beside a stale scanner route and a stale watcher route that must
not reach a Harbor. The rule is the one `index.py` always had, names and ids and states
and counts and never values.

**Capped, and the counts are still real.** The document is not small (190 unarchived
cards, 28 review rows, 13 pull requests on the night this was built), so every section is
capped: 30 card rows per space, 12 reviews, 12 segments, 12 running, 8 queue entries,
titles at 44 characters. Each section carries its REAL count beside its capped sample,
each space a per-stage tally and the reviews a per-lane one,
because the thing spoken most often is a count and a cap that reached one would make it
wrong. That is not hypothetical at either level: the first live turn after this landed
said "three open and the rest behind" about thirteen pull requests, because a fourth open
row sat just past the sample, so the lanes are tallied over every row rather than the
sample. Measured against the live deck: 6,608 bytes, roughly 1,650 tokens.

**Every delivered turn writes down which record it had.** A `digest` line in
`state/voice/transcript.jsonl` carries `source`, `ageSeconds` and `bytes`. A turn holding
the board rather than the deck cannot see the provider rows, and that difference is
invisible in the answer: it reads as a flat "there are no reviews".

**When the deck does not answer.** The gateway falls back to the narrower document built
from `kb list`, `kb needs-you` and `claude agents --json`, and the digest says
`"source": "board"` rather than `"deck"`. The framing says which one it has, so a turn
holding the board cannot answer "there are no reviews" about a screen full of them. This
reverses an earlier shape ("the gateway never talks to the deck"): the deck is up whenever
the phone can reach voice at all, and the gateway already sits behind it as the `/voice/`
tier.

**One lookup verb for both Harbors: `keel deck`.** Stdlib, in `keel/cli.py` and
`keel/deckdigest.py`, importing nothing from the voice package.

| Command | What it prints |
|---|---|
| `keel deck` | one line per section: the source, the cards per space with their stage tally, needs you, running, reviews, segments, the drain line |
| `keel deck --json` | the whole state document |
| `keel deck --digest` | the same reduced digest a voice turn carries |
| `keel deck reviews` | one section as a table; also `cards` (with a `pr` column for a shipping card) and `segments`, each with `--space work|personal` |

It reads the deck over loopback and falls back to building the document in its own process
(`deckstate.build`, the same builder the deck runs), with a note on stderr saying so. The
talker's rulebook names it beside "boot from the board", and the personal contract says
plainly that reading the deck or the board, either space, is not a work tool; ACTING on
work still means filing a work card and saying so.

**The egress split.** Every spoken sentence is sent to Google to be voiced, so
`<install>/memory/talker/speaking-is-egress.md` is real, and until now it was a flat ban on work
identifiers in anything spoken. A flat ban makes a direct answer unanswerable, which is
half of what happened. It splits now on whether the user asked:

- UNPROMPTED speech (narration, a filler, an aside, the refine's sentence, a give-up line)
  carries no work identifier, no ticket number and no customer name.
- A DIRECT ANSWER to what the user just asked may name what the user asked about: a pull request
  title, a story id, a card title. It is the user's phone, on the user's tailnet, answering a question
  the user asked out loud.
- Customer names and credentials stay out of speech either way.

The two sentences are in `harbormsg.FRAMING`, so a turn does not have to recall the memory
to get it right. `REFINE_FRAMING` keeps the unprompted rule verbatim and gets no
exception: nobody asked for a refine, so it is unprompted by definition.

**Answer first, look second** (2026-09-24, lane H, H1). The model answers in 1 to 5 s even
with 160k cached tokens, but the turns where Harbor reached for tools (grepping the Atlas,
`kb`, reading memory files) took 18 to 80 s on the Linux host, mostly for questions the attached
digest already answered. `harbormsg.FRAMING` now says to answer from the digest and what it
already knows, to reach for a tool only when those cannot answer or the user asks it to look, and
then to say one short line first ("Let me check the board."), so the user is not left in silence;
`<install>/memory/talker/voice-turn-shape.md` says the same, and no longer forbids announcing a
lookup. It is prose, so it is MEASURED: every Harbor turn's `harbor-model` stamp carries the
envelope's tool count and `keel voice latency` splits the tier by it (below). On a one-shot
turn the line before a tool is not heard at all (`result` is the last message only, and the
filler covers the wait); on the kept-alive path it is spoken as a part and counted as a
preamble rather than as the answer (see "Harbor's own turns, kept alive and streamed").

## Where a turn's time goes (D-5)

`keel voice latency [--json] [--last N]` reads `state/voice/transcript.jsonl` and nothing
else, writes nothing, and prints p50 and p95 per tier for four stages, each the gap
between two stamps the gateway already writes: **end to transcript** (the listen's end,
which is the detector's `endpoint` record hands-free or the page's `release` trace on push
to talk, to the turn's `said` record: the page's `end`, the speech model and the repair),
**transcript to first words** (to the first `answer-part` of a streamed answer, else the
`answer` record), **first words to first audio** and **end to first audio**, which is what
the user waits. The first audio is the one stamp that was not written before: `Gateway.speak`
puts `firstAudioAt` on its report when the first chunk leaves, and `Dispatcher._say`
writes it once per turn as a `first-audio` record, so turns from before D-5 show no tts
stage. An end record more than 30 s before a turn belongs to another listen; a turn with
none (typed) still counts its model stage. The module is `keel/voicelatency.py`, the
verb `keel voice latency`, the tests `tests/test_voicelatency.py`.

**Harbor's turn, split by its own stamps** (2026-09-24, lane H, H2). On the Linux host a trivial
Harbor turn measured 5.0 s by hand (about 3 s to start `claude`, 1.8 s of model) while the
report said p50 14.8 s, because nothing between `said` and the answer was stamped. The
thread that runs Harbor's turn now writes three records (`voice/harbor_voice/stamps.py`,
called from `harbormsg.one_shot_turn` and `harbormsg.kept_alive_turn`): `harbor-start` when
the `claude` is started (or, kept alive, when the sentence goes down its stdin, `warm:
true`), `harbor-model` when its answer is back, carrying the envelope's `numTurns`, `tools`
(`num_turns - 1`: 1 is an answer with no tool, as `tests/fixtures/harness/turn.json`
records) and `durationMs`, and `harbor-pen` when the board pen is done. A turn that failed
part way writes the stamps it reached. The report adds four stages, printed only where
some turn has them: **transcript to spawn** (the conversation lock, the session, the
framing), **spawn to model done** (process start, model and tools), **board pen**, and
**model done to answer** (the pen, the say inbox and the watch loop). Each tier with a
tool count is reported twice more, as `<tier>, tool-free` and `<tier>, with tools`; a turn
from before the stamps is in neither half. The tests are `tests/test_voicelatency.py`
(`HarborStampsTest`) and `tests/test_voice_stages.py`, which drives the real dispatcher and
the real `send` over a fake `claude` and reads the one transcript back.

**A house turn is the house's** (2026-09-24, lane H, H3). A turn said while the user is connected
writes its `said` record under the house tier (`Dispatcher.answer` reads the pin before the
first record; it used to move the tier one record later, in `_ask_house`), and the report
files a turn under the house for good once any of its records is `connected` or says
`house`, whatever a later record calls it (`voicelatency.tier_of`). Filed by the later
record instead, 5 of 13 turns reported as Harbor's are house turns (measured).

**One TLS connection to Google, not one per clip** (D-5). A clip is one sentence and an
answer is several, and `GoogleTTS._request` used `urllib.request.urlopen` per clip, so
every sentence paid a TCP and TLS handshake to `texttospeech.googleapis.com`.
`GoogleTTS._post` now keeps up to two idle `http.client.HTTPSConnection`s (two, because
a filler and an answer can synthesise at once) and reuses them; a reused connection that
fails before an answer came back (the far end closed an idle keep-alive) is closed and the
request sent once more on a fresh one, only for `RemoteDisconnected`, `BrokenPipeError`
or `ConnectionResetError` and never for a timeout, which may mean Google already has the
text (review item 6); a fresh one's failure is raised as before so
the chain demotes the way it always did. The key still travels in the `X-Goog-Api-Key`
header only. The saving per sentence is not measured here; `keel voice latency`'s tts
stage is where it will show.

## The voice page, a chat you can also talk to (VP, 2026-09-24)

Rebuilt from the research of 2026-09-24 and the user's decisions of the same day (decisions VP-1 to
VP-8). The static PWA is still `segments/voice/app/`, served by the deck, same origin, no
build step.

**The files**, one namespace (`window.Voice`), loaded in this order by `index.html`:

| File | What it holds |
|---|---|
| `voice.core.js` | the flags, the one state object, mode, space and engine, the phrase tables |
| `voice.audio.js` | playback (gapless, the 30 ms cut, the browser floor), the microphone and `closeMic` |
| `voice.link.js` | the socket (one ping timer), the cookie refetch before reconnect (I-9), every gateway message, the bus poll |
| `voice.listen.js` | the hold, the release, the watchdog (V13), the conversation (V2, V3), the gestures |
| `voice.wave.js` | the 32-bar waveform |
| `voice.board.js` | the board a turn drew, through the deck's own embed |
| `voice.view.js` | `displayState`, the bar's label, the header, the dock, the chat |
| `voice.desk.js` | the desk's rail, the "What this turn touched" column and the status chips |
| `voice.sheet.js` | the ⋯ sheet |
| `app.js` | the wiring, the test door, and go |

`app.css` sits on the deck's own `/ui.css` and `/ui.plan.css` (the palettes, the reset and
the board embed), with every class of its own prefixed `v-`.

**The composer.** At the bottom, a wide field ("Message Harbor", growing to four lines) with
a + menu at its left and the hold-to-talk mic at its right. Enter sends a `text` line, which
the gateway answers in TEXT ONLY (see "A typed line is a typed turn" above); the transcript
marks the turn "typed". Holding the mic opens a push-to-talk listen and turns the composer
into the voice bar; letting go sends `end`; the bar stays through thinking and speaking and
its keyboard button returns to typing. On the desk, Space holds whenever no field has focus,
Esc cuts, `r` asks for it again aloud, and `/` goes to the field.

**Push to talk is where it rests.** The + menu holds the two rare things: Conversation
(hands free, unchanged, ended by the pill above the composer, "that's all" or the menu) and
Capture next (one hold filed as a card in the chosen space, then back to talk). There is no
Capture and Talk toggle any more.

**The voice bar never lies.** Its label is what the next touch does: "Hold to talk" (or "Hold
to talk to c-272", or "Hold to capture to personal"), "Opening the microphone" until the first
frame, "Release to send" with a timer, "Harbor is thinking" with the turn's seconds (and its
eta when Harbor gave one), "Hold to cut in", and in a conversation "Listening, tap to pause",
"Paused, mic closed. Tap to resume", "Microphone stalled, tap to reopen", "Go on" for a held
half sentence, and "Voice is down. Tap to retry". One line above the composer says the most
important other true thing: the gateway down and since when, speech not ready, a stall, a
pause the lock screen made, a note.

**What a turn touched comes back as a receipt.** A capture is a row to its card on the deck.
A board a turn drew is the REAL board, Harbor's or a connected house's (VP-8): the say
record carries its ids, the page reads the
board's lines from `/api/board/<id>` and hands them to the plan pages' own embed
(`K.planBlocks.block`), loaded from the deck the first time it is needed, with Open board and
"What hangs on this board"; a tap opens `/board/<id>?full=1`. On the phone it sits under the
latest answer and older ones are one-row receipts; on the desk it fills the right column.

**Its icon is the lighthouse with sound arcs** (c-518), gold on navy, and Harbor's own
lighthouse, bare and in the accent, marks Harbor's name in the header and the "Talk to" rail. Both come from the glyphs
in `app/icons/src/` through `app/icons/build.py`, which writes Voice's set into
`segments/voice/app/icons/` ([the deck](40-deck.md), "The icons").

**Phone and desk differ on purpose.** The phone is one screen: a back link to the deck (with a
dot when a decision is waiting, Q4's static mark), who the user is talking to (Harbor, with its
lighthouse, or the card id in its space's colour with the hold's ring), REC while `[voice] record` is on, and the ⋯
sheet; then the chat and the dock. The desk is the studio: the header's status chips (STT,
TTS, REC, judges, a waiting decision), the rail "Talk to" (Harbor, then every card the deck
lists as a house, one tap to connect through the same `connect` the spoken phrase sends) with
this session's receipts, the chat in a 720px column, and "What this turn touched" (the board,
else the card the user is connected to with its plan's round and links into the deck). The page
acts once and only once: the user's answer to one of Bosun's asks, said back and confirmed, which it
posts to `/api/action` with `voice: true` (c-523; `actions.voice_answer` refuses the flag on
any other body). `bin/keel-voice-selftest` names that one call site (`ANSWER_SITE`) and fails
on any other call to `/api/action` in the voice front end, and on that one turned into
another verb; it proves both on copies every run. Otherwise it reads the live part of `/api/state` (c-549), `/api/board` and `/api/plan`, and every
control that would change the board is a link into the deck.

**Alive, not busy.** The waveform's levels are real (the user's from the worklet's frames, Harbor's
from the bus's `level` and `samples`), and direction says who is talking: inward while the user
speaks, outward while Harbor does, a slow breath at rest, a sweep while thinking. Nothing is
drawn while the page is hidden (the render is owed and done once when it is seen), the bus is
polled every five seconds while hidden, and reduced motion stops every animation.

**Kept exactly:** the socket protocol and every URL parameter (`?connect=`, `?listen=1`,
`?listen=once&mode=capture`, `?space=`, `?engine=`, `?selftest=1` and `window.__voiceTest`),
flags.js as the one home of the page's answers, the cookie refetch before reconnect, the iOS
unlock inside the first gesture, and pause meaning the microphone is closed.

**The tests.** `tests/fixtures/voice-listen.js` drives the real scripts under node (the
watchdog, the ceiling, presence, the composer, push to talk, Capture next, the menu's
Conversation, the single ping timer, a hidden page, the board handed to the deck's embed);
`tests/test_voice_page.py` holds the rules with no behaviour to run (its one action, the deck's
embed and sheets, the budgets); `tests/test_voice_typed.py` the gateway's typed turn and the
boards a turn names.

## What moved from Harbor's voice tree

| Was | Is |
|---|---|
| `~/harbor/bin/harbor_voice/` and `~/harbor/bin/harbor-voice*` | `voice/harbor_voice/` (plus `voice/harbor_queue_fold.py`, the shared fold the instant answer counts through) and `bin/keel-voice*`; the gateway launcher lost its install, uninstall, status and venv verbs to `keel voice` |
| `~/harbor/.venv-voice`, `~/harbor/etc/voice-requirements.txt` | `.venv-voice` (built fresh, 3.12.11), `etc/voice-requirements.txt` |
| `~/harbor/segments/voice/data/` (inboxes, transcript, TTS meter) | `state/voice/`; the rendered filler audio under `state/voice/cache/filler-audio/` |
| `~/harbor/ledger/voice.log` | `state/logs/voice.log` (the old log copied in as its head) |
| `dev.harbor.voice`, plist rendered by the old gateway script | `dev.keel.voice`, `dev.keel.voice.plist` in `etc/` from `keel voice install` |
| `~/harbor/segments/voice/{segment.md,card.html,service.json,app/}` | `segments/voice/`, served ahead of `segments_dir` |
| `~/harbor/etc/dictation-vocabulary.md`, `~/harbor/identity/about-<name>.md` | `etc/dictation-vocabulary.md`, `<install>/identity/about-<name>.md` (the rulebook, the memory index and the notes that name it point at the install's copy once the memory card c-727 lands, and the personal contract once its owner edits the line naming it; from the deploy after c-726's, the preflight refuses a tree while either still names the checkout, c-726 r1.F1, r1.F6) |

The old Harbor-era voice tree is left as it was and nothing here reads it.

## Where it lives

- `keel/talker.py`, `spaces/harbor/.claude/`, `talker/`, `dev.keel.talker.plist` in `etc/`.
- `voice/harbor_voice/verbs.py` (the phrase table, the id parser, and the connect
  directive), `voice/harbor_voice/harbormsg.py` (the framing the key rides in).
- `keel/converse.py` (the connected turn, the hold, and the BOARD half of a turn),
  `keel/housetalk.py` (the MACHINE half: the kept-alive conversations `keel serve` owns),
  `keel/housetier.py` (the `/api/house/` routes and the client that calls them),
  `keel/sentences.py` (where a spoken sentence ends), `keel/narration.py` (what a streamed
  house turn is allowed to say, and where a part of the answer is left),
  `voice/harbor_voice/connected.py` (the gateway's side of it),
  `<install>/history/docs/probes/conversation-probe.py` (the recorded measurement), and the tests
  `tests/test_converse.py`, `tests/test_housetalk.py`, `tests/test_housetier.py`,
  `tests/test_sentences.py`, `tests/test_narration.py` and `tests/test_voice_connect.py`.
- `keel/voice.py`, `dev.keel.voice.plist` in `etc/`, `etc/voice-requirements.txt`, and the
  gateway: `voice/harbor_voice/` (the Linux ONNX engines in `voice/harbor_voice/onnx.py`, an
  adapter's mishearings in `<install>/packs/work/hearing.json`), `bin/keel-voice-gateway` (what launchd runs),
  `bin/keel-voice` (the say, opening, progress, ask, state and health commands),
  `bin/keel-voice-selftest`, `bin/keel-voice-corpus` (the filler lines: check, render,
  score), `bin/keel-voice-vocab` (regenerates the harvested half of
  `etc/dictation-vocabulary.md`, which is what `hearing.py`'s repair targets are checked
  against, so it outlived the tier its name suggests) and `bin/keel-voice-filler-score`
  (the filler's guard, against its attack sets). The two scorers that read the deleted fixtures,
  the router's and the conversations', went with the tier they scored.
- `segments/voice/`: `segment.md`, `card.html`, `service.json` and the PWA under `app/`.
- `keel/voicelatency.py`: `keel voice latency` (D-5), below, and
  `voice/harbor_voice/stamps.py`, the Harbor turn's own stamps it reads (lane H).
- `keel/voicetier.py`: the `/voice/` tier, mixed into the deck's request handler in
  `keel/serve.py`. the install's `config.toml`: the `[voice]` table.
- `keel/deckdigest.py`: the loopback read of `/api/state` (and of `/api/boards`, for a
  connected turn's receipt, VP-8), the fold, the digest's caps and
  the tables `keel deck` prints. It is the one file the voice package imports out of
  `keel/`, and it imports nothing from `keel/` itself so that stays safe.
- `<install>/history/docs/talker.md`: what was built and what was verified, with the raw probe output.
- `<install>/history/docs/voice-two-modes.md`: the plan the gateway is being built towards.
- `tests/test_talker.py`, `tests/test_voice.py`, the voice tier tests in
  `tests/test_serve.py`, and `bin/keel-voice-selftest` under `make test-all`.

## How to change it

- The rulebook is `memory/talker/CLAUDE.md` in the install (shipped as
  `templates/memory/talker/CLAUDE.md`), and it is the talker's whole behaviour.
  Keep it short: it is injected into every turn of a conversation that runs for weeks.
- A change to how the server is started or read belongs in `keel/talker.py`, with the
  recorded bytes in `tests/test_talker.py` as the fixture. Do not probe the live session to
  find out what it prints; the recording is there.
- A change to the gateway's behaviour is a change under `voice/harbor_voice/`, run from
  `.venv-voice`, with `bin/keel-voice-selftest` as its guard; `<install>/history/docs/voice-two-modes.md`
  says what is planned. A change to where it runs or what it is given is `keel/voice.py`
  and `tests/test_voice.py`, then `keel voice install --load`. If the shape of the state
  document changes, `keel/deckdigest.py` is what has to follow, and it is ONE file for
  both readers on purpose: `keel deck` and a voice turn must never describe different
  boards.
- A change to WHAT IT SOUNDS LIKE is one table: `config.voice_id` in
  `voice/harbor_voice/config.py`, one voice per engine since V13. A change to WHOSE VOICE
  speaks at all is one function beside it, `config.voice_speaker`, which is where the
  second voice was taken out and where one would go back in. A voice changed there
  invalidates the clips rendered in the old one, so it is followed by `keel voice audio
  --render`, and the old clips simply stop being asked for, because the cache key is built
  from the voice. Check the new name exists before shipping it: the chain demotes by
  ENGINE, so a voice id the API does not know takes that engine down entirely.
- A new service behind the deck is the same shape as voice: a port in the install's `config.toml`, a
  prefix routed in `keel/serve.py` (the voice tier's own code is `keel/voicetier.py`), and
  `keel doctor` told about it.
