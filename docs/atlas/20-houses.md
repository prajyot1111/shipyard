# Houses

A house is one background Claude Code session working one card, start to finish. It runs
in its own worktree, writes its record into the card's directory, and ends its turn at a
gate. Nobody watches its terminal: what it does not write to the card, nobody sees.

## How a house starts

`keel/house.py` assembles three things, then `keel/harness.py` runs `claude`.

1. **The placement.** `worktree_for` asks the space's adapter for the worktree (work) or
   cuts a `git worktree` under `state/worktrees/<id>` (personal), recreating from the
   existing branch when the directory is gone. A repo an install cloned into its layout
   (`.../spaces/<space>/<key>/repo`, [onboarding](89-onboarding.md)) cuts at
   `<key>/trees/<id>` instead (`repolayout.card_tree`, `adapters.worktree_dirs`), so the
   repo and space tiers above it load; the merge, Drop in and the review gate find it
   there too. An errand (no `repo`) runs in `state/cards/<id>/` instead.
2. **The settings file**, `state/cards/<id>/settings.json`, passed with `--settings`:
   - `hooks.Stop` runs two commands in one group: `kb stop-check <id>` (the nudge budget
     at building) and `bin/keel-turn-end <id>` (the record at the outcome gate, the
     discussion flag, and the card's news, in `keel/ending.py`).
   - `hooks.SessionEnd` and `hooks.Notification` (matcher `idle_prompt|permission_prompt`)
     run `kb event <id> --hook ...`, so the board learns the process ended or the session
     is waiting without the session remembering to say so. A `permission_prompt` is how a
     house paused by auto mode past its denial limit reaches the user's needs-you
     ([the drain](30-drain.md), "A house auto mode paused on a permission prompt").
   - `hooks.PreToolUse` keeps the machine's stack-invariants guard, when that file exists,
     and every house with an open shell (a repo card) also runs Keel's own house guard,
     `bin/keel-house-guard` ("A wait loop on pgrep -f is refused", below).
   - `claudeMdExcludes`, for a repo in the install's layout only: absolute globs for
     the team's CLAUDE.md files in its clone and in every worktree
     (`repolayout.excludes`), so the house reads the tiers and never the team's file
     ([onboarding](89-onboarding.md)).
   - `permissions.deny` is the space's deny list, then the machine's own secrets
     (`house.secret_deny`, card c-451): `state/human.token` and `state/house.key`, each as
     `Read(//<absolute path>)` (the DOUBLE leading slash of decision H6) and as `Bash`
     patterns naming the path and the bare file name. `human.token` is the user: a house that
     read it could hand it to its own `kb` and approve its own gate. The shared key
     (`housetier.shared_path`) is denied too, as `Read` and `Bash` on its path (c-522):
     Bosun's key is derived from it, so a house holding it could make its `kb` say `bosun`.
     **This is not a
     boundary, and the page says so plainly:** the rules bind Claude's own tools, so a
     same-user shell can still spell the path another way, or run a program that opens
     the file. Every house runs as the same Unix user as the deck, and a same-user process
     can read any file that user can. Separate Unix users for the houses are the real
     boundary, and a later card. The deny makes the plain attempt fail and says whose the
     file is; the deck's cookie ([the deck](40-deck.md), who may act as the user) is the other
     half. The token is not handed over in the environment either: `harness.child_env` and
     `harness.scoped_env` drop `harness.WITHHELD` (`KEEL_TOKEN`, `KEEL_LIVE_STATE`) from
     every environment a `claude` is started with, and the deck runs `keel drain --once`
     (Retry, create and start) with `actions.deck_env`, which has no token. Only the `kb`
     the deck runs itself (`actions.kb_env`) carries it. The rule lives in
     `keel/childenv.py` and every other child is built through it too: the suite and every
     git call of a merge (`keel/merging.py`, which runs inside the kb the user's Approve started),
     the landing worker, a board's ask, the talker, and the voice gateway's Harbor turns.
     The space's adapter may add entries for this card too (`adapters.extra_deny`, the
     adapter's `deny <id>` verb with the card on stdin; a verb that fails refuses the start
     rather than starting an unfenced house). The work adapter takes pushing and pull
     requests away from a research card this way.
   - `permissions.allow` is the space's allow list (`[spaces.<name>] allow`, c-769), for a
     house with an open shell (a repo card, except a fork's review card, which is
     confined) whose space names one; a space that names none writes no `allow` key. Only
     the space's own table may name it: a pack's `[space]` that carries `allow` is a
     warning at load and is not read, and a value that is not a list of non-empty strings
     is a warning and no rule (`config.space_allow`). Under `--permission-mode auto` a command no rule settles goes
     to Claude Code's classifier, which can refuse a house the space's own test command;
     an allow rule is read before the classifier, so the command the space sanctions runs
     unasked. A deny still wins: every entry of `permissions.deny` above beats an allow,
     and the allow list never changes the deny list. The house's PreToolUse hooks still
     run on an allowed command (the house guard, the pack's `guard`), and their refusal is
     relied on here as it is for every command the classifier passes; nothing in Keel
     tests that order. An allow rule names only commands that need no guard behind them
     (a test command, never a push or a pack's tool): `bin/keel-house-guard` fails open on
     its own error and when the harness stops it at twenty seconds, and a guard that fails
     open leaves an allowed command with nothing behind it. A
     confined house gets no allow list: its Bash is the board's by the fence, and its tool
     set and the paths it reaches are not the space's to widen. The builder's own session
     does not take it either ([Bosun](96-bosun.md)): its allow rules are its own.
   - `env` carries `KEEL_CARD`, `KEEL_CARD_DIR` (the card's own directory,
     `<state_dir>/cards/<id>`: every brief, the contract and the adapters' briefs name it,
     never `$KEEL_HOME/state/...`, which is wrong wherever `state_dir` is elsewhere, the
     sandbox's; houses there reset `KEEL_HOME` to find it and broke `kb` and `pr`, c-604),
     `KEEL_HOME` and a PATH with `bin/` first. **A rewrite of this env does not reach a
     LIVE session** (probed 2026-09-30 on 2.1.285, c-604 review: a throwaway `--bg` haiku
     session with `KEEL_PROBE_X=one` in its settings, the file rewritten to `two` while it
     sat idle, then told through `relay.tell`, still printed `one`). It should take effect at the
     next start or `--resume` (not probed). So words TOLD into a live session (a review batch,
     `shipround.batch_prompt`; the tell's pointer) name the card's directory by its absolute
     path, never `$KEEL_CARD_DIR`; only the brief, read at a start or resume, uses the
     variable. This has to be
     in the settings file: `claude --bg` claims a session process that a per-config-dir
     daemon pre-spawned, so the process environment a house sees is the daemon's, frozen
     at its first start.
     Under a toml of its own (`KEEL_CONFIG`, the demo sandbox's) it also carries
     `KEEL_CONFIG` (`house.named_toml`), or the hooks' `kb` and `keel-review-stamp` load
     the checkout's own toml and write to that checkout's board (c-570). The checkout's
     own toml and a scratch config are never passed, so a house in a Keel worktree keeps
     its scratch board.
   - **Every hook command pins its board on its own command line** (`house.board_prefix`,
     c-601): `KEEL_HOME=<root> KEEL_CONFIG=<toml or empty>` ahead of
     each `kb`, `keel-turn-end` and `keel-review-stamp`. A hook runs with the daemon's
     environment, and without this a sandbox house's Stop hook can end up
     opening the LIVE board (c-601). Empty reads as unset for both, so a stale inherited value is
     overridden rather than left to win over the toml.
3. **The brief**, written to `state/cards/<id>/brief.md`: the contract, the generated
   "What you can do" block, the card block, the space contract, and for a work card the
   adapter's own half.

`launch` then starts the session, records a `session` event, and stages the card
`planning` (attended) or `building` (autonomous). A start that fails blocks the card with
the reason. **One house per card, whichever path starts it** (c-601): `launch` is wrapped
(`house.one_house`) to hold the card's lock (`house.card_lock`) and read the card again
under it, and one no longer at the stage its caller expects (`expect`, `assigned` by
default; a caller that starts a house at another stage, a shipping card's first batch,
passes that stage) or blocked is `house.AlreadyStarted`, which the drain logs and passes over. A claim by
this host is a no-op, so the deck's Retry (its
own `keel drain --once --card`) and the looping drain on the same machine both started a
house on one card in the e2e run; Retry now reads a card the loop started first (a new session, whether its own pass
answered, refused or outran the deck's wait) as done.

**Never a twin beside a live house** (c-605). Retry on a card whose house was still listed
started a second session and left the first alive. Now the deck's Retry refuses first,
before anything is unblocked, reset or relayed (`actions.refuse_live_house`): it asks the
listing, and a recorded session listed with a process (`house.live_twin`) answers "Stop it
first, or use Resume", and nothing is reset. `one_house` asks the same under the
card's lock, so a start that races a live house raises `house.LiveHouse` instead: the
drain notes it on the card once and starts nothing. Nothing automatic stops the old house.

**A done card is never resumed** (`house.refuse_if_done`, in `house.resume` and before the
deck's `house.resume` relays): its worktree is reaped, and a resume ran a real turn there,
recreating the directory, with nothing on the board (c-601). A resume or rotate relay
still pending when the card reached done is superseded by the drain with a note on the card
(`drain.DONE_WHY`), never carried into that refusal and a failed-resume block.

**The cwd is trusted first.** Claude Code 2.1.281 refuses `claude --bg`, and `claude
--resume <id> --bg`, in a directory its config dir has not trusted ("Workspace not
trusted. Run `claude` in <cwd> once and accept the trust prompt"), and every house cwd is
new, so a card blocks on exactly that (c-452). So
`keel/trust.py` writes `projects[<cwd>] = {"allowedTools": [], "mcpServers": {},
"hasTrustDialogAccepted": true}` into the `.claude.json` that config dir's claude reads
(`trust.file_of`: `<config_dir>/.claude.json` for a dir reached with `CLAUDE_CONFIG_DIR` set,
and `~/.claude.json` for the default `~/.claude`, which Keel reaches with the variable UNSET,
`harness.point_env`; writing `~/.claude/.claude.json` there made every start fail untrusted,
c-601), merged with
any entry already there, right before every `start_bg` (`house.launch`,
`rotate.start_fresh`), every `resume_bg` (`house.resume`) and every `wake`. It writes
through `keel/claudejson.py`: one atomic rename (a temp file renamed over it), and the file
is read AGAIN and the entry applied to that just before the write (`trust.rewrite`), since
live claude processes write the same file: a write of theirs is lost only in the moment
between that read and the rename, not across the whole call (c-601 review), and never over a file that does not
parse, which blocks the card with that reason instead (the file holds the login). The
entry goes again when the directory does: `merging.land_card` forgets a worktree it
reaped, and `house.retire_finished` an errand's card directory. Only a path under the
state dir is ever removed, so an entry Keel did not add is never touched. `claude -p` (a
connected turn, a voice ask) does not check trust, so those paths write nothing. What
2.1.281 does, inheritance from a parent directory included, is in
`tests/fixtures/harness/README.md`.

**Every house names its model.** `harness.session_flags` always passes `--model` and
refuses to build a command line without one, because `claude` given none runs on the
account's own default (c-434: c-272 ran five days on Fable). Every card leaves create with
a model ([cards and gates](10-cards-and-gates.md), "Where a card's fields come from"), and
a card that still has none, one filed before that or imported, is refused by
`house.require_model` at launch and at resume alike: blocked with the reason and the
`kb set <id> model=<name>` that fixes it, never started on a guess.

**The session is declared to csr.** After a launch, and after a resume that minted a new
session, `keel/sessionorigin.py` writes csr's sidecar for it,
`~/.claude/session-origin/<session id>.json`, `{"provenance": "house", "origin_ref":
"<card id>", "topic": "<topic>"}`, which csr reads as ground truth for which work item a
session belongs to. It is written only where that directory already exists (a machine
without csr gets nothing created), and a file that cannot be written is skipped rather than
failing the launch.

## What a house is given

| Piece | Where it comes from | What it says |
|---|---|---|
| The contract | `etc/house-contract.md`, under 60 lines, or `etc/house-contract-drop.md` for a house with no shell | The two gates, keeping the record, where it may act, how to end a turn |
| What you can do | generated by `keel/prompts.py` from `kb help` | The board's verbs, minus the ones a house must never call, plus the child-card form, what the human can see from the deck, and for a house with a shell the drawing board's verbs and current grammar card (`boardgrammar.brief_block`, c-603) |
| The card block | `keel/briefnews.py` | A fenced JSON of the card's fields, and `KEEL_CARD`; rewritten as a change reaches the house (below) |
| The space contract | `etc/space-work.md` or `etc/space-personal.md` | The credential boundary, the delegation rule, the writing rules; the personal one also says what a research, plan or errand house delivers and that it runs no code pipeline (c-593) |
| The adapter brief | `packs/<name>/brief <id>` (the space's adapter dir) | The worktree, the isolated test and preview tools, the story, the options, the ending |
| The theme | `app/theme-work.css` or `app/theme-personal.css`, copied to `state/cards/<id>/theme.css` | The palette every surface it writes links |

**The brief never promises what the tool set denies**, which is the rule the two files and
the three shapes of the block exist for. A repo card gets the contract, the verbs, the plan
section (the format card with `plan_pages` on; the plan styles, the surface and the
annotation poll with it off) and the surface for a report or a mockup. A fenced errand gets
the contract, the verbs, the plan section, the fence's own sentence, and markdown rather
than a surface, because `lavish-axi` is not one of the commands it may run. A house with NO Bash gets `etc/house-contract-drop.md` and one section
that names the file it writes: no verb list, no `kb`, no surface, nothing it could not do.
`prompts.has_bash` is the one place that decides which, so the brief and the confinement
cannot drift apart. A confined house whose tools include `WebSearch` or `WebFetch` is
also told the web is there (`prompts.web_block`), in either confined shape.

The verb list is generated rather than written down because `cli.VERBS` is the one place
verbs are defined. `kb help` is run with the house's own environment, filtered of
`approve`, anything named like `stop`, `import-harbor`, and the operator roles. A `kb help`
that exits non-zero falls back to a short hand-written list and says so in the drain's log.

## The plan flow

An attended house writes the plan first and stops:
`kb stage $KEEL_CARD planning --plan <path>`. The plan goes under
`$KEEL_CARD_DIR/`, never in the worktree. Its FORM is the brief's own section
("How you write the plan and the outcome", `keel/planbrief.py`), not the contract, so one
switch decides it. With `[keel] plan_pages` on (it ships on) the section carries the plan
format's card, generated from the parser (`keel/plancard.py`), and says: write `plan.md` in
the format, `kb lint` until the contract holds before the stage (which refuses it
otherwise), flows are boards (`keel board list --card $KEEL_CARD` first, then `keel board
push --card $KEEL_CARD --new --file <ops>` for new ones, embedded by id, as rich as the
house's context allows), and answer an Ask with `kb reply` without revising the plan or
moving the card. The record, `context.md`, starts as an outcome in the format (its
frontmatter written by `house.ensure_context`), so `kb stage review` lints it too. The
lavish lines of the brief are left out: the user's round arrives through the gate verbs.
With it off, the card's `options.plan_style` picks the form: `lavish` is a surface (load the `lavish` and `html-artifacts` skills; it has to
be opened with `lavish-axi --no-open <file>` before the turn ends, or there is nothing to
annotate),
`markdown` a page, and `auto` lets the house choose, a surface when there is a design
choice or several shapes to compare, a page when it fits in one. An autonomous house writes
the plan too, sets it with `kb set`, and carries on.

**Every open question carries a recommended answer.** The contract asks for it
(`etc/house-contract.md`), because a plain Approve means "go with your recommendations":
the approve prompt says in one sentence that a question the user did not answer takes the plan's
own recommendation and that the house does not stop to ask again. What the user DID answer
arrives in that same prompt, quoted, when the user tapped Approve with something typed beside it
([the two gates](10-cards-and-gates.md)), and the prompt then tells the house to apply the user's
answers where they change the work and to say in `context.md` what changed. On a lavish
plan the annotations and the user's words are read together, as one answer.

**Annotations are collected on resume, never by a waiting house.** Lavish queues what the
human marks up and hands it over only through `lavish-axi poll`, which long-polls in the
foreground. So the approve and send-back prompts open with ONE bounded poll
(`timeout 20 lavish-axi poll <plan>`) for an HTML plan. A house never sits in a poll on
the chance something arrives: waiting is the drain's job, and a killed poll loses nothing
because lavish keeps the queue.

**Discussion mode is the exception.** "Send back and stay" keeps the card at `planning`
with its gate open, records `options.discussion`, and hands the house a poll, reply, poll
loop bounded by `discussion_idle_seconds` (1200). The house holds a slot on purpose: the user
asked for the conversation. It counts because it was resumed and has not ended that turn,
and its poll is a running tool call; once the turn ends it idles at the gate and holds none. `end_discussion` ends the lavish session so the house's own
poll returns and its loop ends naturally. It never ends the session itself.

## What a surface a house writes looks like

The deck is this project's design system, and a plan is a surface of the same board, so it
carries the same palette: cool in the work space, warm in the personal one. Two standalone
stylesheets say so, `app/theme-work.css` and `app/theme-personal.css`. They are dark, they
paint the page surface themselves, and they style plain semantic HTML (headings,
paragraphs, tables, lists, code, quotes) plus `.panel`, `.tile`, `.pill` and `.grid`, on the
deck's own budgets: four type sizes, two weights, a 4px grid, square boxes, soft pills.

**Two files rather than one switched by an attribute.** A lavish artifact is a fragment with
no `<html>` element to carry a `data-space`, so an attribute-switched theme renders in the
wrong space, or unstyled, every time a house forgets it, and it fails silently. The space is
already known where the file is chosen (in Python, at launch), so choosing the FILE there
leaves the house one thing to do: link it. The two files are identical below the palette and
`tests/test_theme.py` holds them there. It compares every token against the matching
`html[data-mode="..."]` block of `app/ui.css`, compares the two shared sections byte for
byte, and measures every text pair against 4.5:1. They duplicate the deck's tokens on
purpose: a plan has to render standing alone, with no deck and no Tailwind.

**Copied at start, not asked for.** `house.ensure_theme` copies the space's file to
`state/cards/<id>/theme.css` from `brief_for`, and again on every resume so a palette change
reaches a card that is already open. The house only has to link it:

```html
<link rel="stylesheet" href="theme.css">
```

Relative, and beside the HTML: lavish serves a surface's local assets from the surface's own
directory, and an export inlines what sits beside it. `prompts.SURFACE` says that in the
brief, names the copy command for a surface written somewhere else, and says this theme
overrides lavish's own "decide the design direction" priority list. The contract says
nothing about it (c-603). The deck serves both files as well (`/theme-work.css` and
`/theme-personal.css` in `serve.APP_FILES`), so a surface opened through the deck's origin
can reach one.

## A house never opens a browser

A plan that pops open a browser tab when it is ready is only useful to someone at the desk;
for anyone else it is clutter.
A house's surfaces are read from the deck, on a phone as often as at the desk, so nothing a
house runs opens a window on this machine. Two mechanisms, because only one of them survives
a lavish upgrade.

- **The shim.** `etc/house-bin/open` is an `open` that opens nothing: it appends the URL to
  `state/cards/<id>/opens.log`, puts it on the card with `kb note`, and exits 0 so the caller
  carries on. `config.house_path` puts `etc/house-bin` ahead of `bin` on a house's PATH, in
  the settings file (`house.env_for`, which is what the house's own shell sees) and in the
  launch environment (`harness.child_env`). Only a house is given that PATH, so a human's
  `open` is the real one.
- **What lavish offers.** Nothing in `lavish-axi --help`, but two real switches, both probed
  on 2026-09-17 and recorded in `tests/fixtures/harness/README.md`: the flag `--no-open`
  (which the brief now uses) and the variable `LAVISH_AXI_NO_OPEN=1` (which
  `env_for` and `child_env` both set). With neither, lavish reaches the browser through the
  npm `open` package, which on macOS spawns the bare name `open`: PATH decides, so the shim
  catches it.
- **The talker is not a house.** `keel/talker.py` and `spaces/harbor/.claude/settings.json`
  are deliberately left alone. The talker is the session the user speaks to at the desk, and
  opening something for the user there is the point.

## The one browser tool

A house that changes HTML or CSS is told to render it ([the deck](40-deck.md)). A
tool outside this repo (`harbor-browser`, on one user's machine)
drives the Google Chrome installed on the desktop, which a headless host does
not have. A house building on such a host (c-310) would have to hand-build one inside its worktree to
reproduce a CSS bug: Playwright's Chromium, eight shared libraries fetched into a local
sysroot behind `LD_LIBRARY_PATH`, DejaVu behind a local `FONTCONFIG_FILE`, about 230 MB, all
of it thrown away when the worktree is reaped. `bin/keel-browser` is that work done once.

- **The same command line, deliberately.** `shot <url> <out.png> [--full-page]`, `dom <url>`,
  `requests <url> [--seconds N]`, `eval <url> <js>`, with `--settle`, `--timeout`, `--width`,
  `--height` and `--wait-for` anywhere, and the same exit codes, 6 for a `--wait-for` that
  never became true. Anything written against `harbor-browser` runs here unchanged, and on
  `harbor-browser` keeps working for everything outside Keel.
- **A fresh context every run.** No profile, no cookies, no saved session, no extension. Keel
  can LOOK at a page and cannot BE the user on one, so everything behind a login is invisible
  to it. That is what makes it safe to hand to an unattended house, and it is why the browser
  extension that drives the real logged-in Chrome is denied by name in the install's `config.toml`.
- **Torn down on every exit path.** The engine, `bin/keel-browser.js`, closes the browser in
  every catch, in its own watchdog and on a closed pipe, because the tool it was ported from
  exists after a leaked-Chrome incident took a Mac's swap to 17 of 18 GB. The wrapper adds
  what a timer inside node cannot cover: the engine runs in its own process group, and a hard
  timeout a slack past the engine's own budget kills the GROUP (TERM, then KILL five seconds
  later). Killing the leader alone is what leaves Chromium children parented to init, and on
  12 GB that is voice latency. The slack and the grace are `KEEL_BROWSER_HARD_SLACK_S` and
  `KEEL_BROWSER_HARD_GRACE_S`, which only the tests shorten.
- **One Keel-owned place per machine**, `~/.keel-browser` (`KEEL_BROWSER_HOME`), holding the
  node package and the chromium build. Not a worktree, which is reaped; not `state/`, which is
  backed up nightly and does not want 400 MB of regenerable bytes in every snapshot; not
  another project's directory. A missing install is not a stack trace: it names the command
  that fixes it and exits 7, its own code.
- **Installed by `bin/keel-browser install`**, which is where the pinned Playwright version
  lives, and reported by `keel doctor`
  through `keel/browser.py`: on a host with `browsers_max` and spaces to serve a missing
  browser is named, and elsewhere the line reads "not applicable".
- **Tests only, until the repo's file says how to run the app** (c-678, the first-run
  design's decision `testsonly`). A repo the install copied has a run rule only once its
  adopted CLAUDE.md has a line beginning "Run the app:" (`repocommands.run_rule`,
  [onboarding](89-onboarding.md), "What Keel does with an adopted file"). Until then:
  - **the mechanism**: a card on that repo cannot carry `options.browser`. The board refuses
    it at create, at a set that turns it on, and at a set that moves a browser card onto
    the repo (`Board._refuse_browser`, asked through the `run_rule` the board is opened
    with, `repocommands.runs`): "<key>'s CLAUDE.md does not say how to run the app yet, so
    a card on it cannot take the browser: sessions there run tests only until it does". So
    no house that the drain gives a browser slot starts on such a repo;
  - **the words**: the house's brief gains a "Running the app" section (`house.app_block`,
    `prompts.TESTS_ONLY`): run the tests only, start no app, no dev server and nothing that
    listens on a port, and say so on the card where the work cannot be checked without it.
    "Do not start the app" is not something a permission rule can deny, which is why the
    browser is the part held by mechanism.

  Once the file names the command the section says it instead (`prompts.RUNS_APP`), and a
  card there may take the browser. A repo outside the install's layout has no such file:
  the board asks nothing of it and its brief has no such section, as before.
- **`video` plays a scene** (c-570, for the demo video): `keel-browser video <url>
  <steps.json> <out.webm>` runs a steps file of `click`, `type`, `scroll`, `wait`, `eval`,
  `goto` and `hold` steps and writes three things named from the clip: the webm at the
  viewport's size, `<out>.stills/NN-label.png` after every step at the file's `scale` (2x by
  default, so an edit can push in and stay sharp), and `<out>.timeline.json`, each step's
  start and end on the clip's clock, the box of the element it acted on, the box of every
  element the file `names`, and the page's text (what the demo's employer sweep reads). The
  grammar and the timeline are `bin/keel-browser-steps.js`, pure JavaScript, so
  `tests/test_browser.py` holds them with a bare node; the whole file is checked before a
  browser starts, and a step that fails still writes the timeline of the steps before it.
  A file's `mic` names a 16-bit WAV that Chromium's fake capture device plays as the
  microphone, which is how a spoken line becomes a real voice turn, and its `css` is a
  stylesheet on every page from before the first paint (an init script), for what a clip
  must never show even for a frame. Its default budget is
  600 s, not 60. The demo's scenes and their recorder are `demo/scenes/`.
- **A card that drives it declares `options.browser`**, which is what the drain's browser slot
  counts ([the drain](30-drain.md)). The brief's surface section (`prompts.SURFACE`) says both halves:
  this is the only browser tool, and a house does not start one without the slot.

## A house's worktree has its own board

A house working on Keel itself builds in `state/worktrees/<id>/`, which carries no config of
its own: it reads the shipped example, `etc/shipyard.example.toml` (c-722 landing B), and a
house's environment names the install's `config.toml` (`KEEL_CONFIG`), whose `state_dir` is
the LIVE board's. Left at that, anything the house runs from that worktree that loads a
config naming the live state opens the user's board: a scratch voice gateway run from a worktree, isolated
with its own `KEEL_HOME`, port and PATH, files every capture spoken into it as a
real card on the live board, and the test fence catches `bin/kb help` reaching the same place from
the other side. The rule and its one override are on [the start page](00-start-here.md);
what a house sees of it:

- **The worktree gets its own scratch board.** `bin/kb`, `bin/keel serve` and a voice gateway
  started from the worktree all open that worktree's `state/board.db`, which did not exist
  before, and each one says `scratch` in its first line. The worktree's `state/` is
  gitignored like any other.
- **`KEEL_HOME` in your environment does not change that.** The
  drain hands every house `KEEL_HOME=<the live checkout>`, and the first version of this rule
  read the code root off that name, so a `kb` or a gateway run from the worktree still opened
  the user's board: `bin/keel-voice-selftest`, which houses run to prove their voice work and whose
  capture checks speak two phrases and expect cards back, filed 84 real ones in a day, 69 of
  them from one card. What decides now is where the RUNNING PACKAGE lives, which no variable
  can move. `python3 <worktree>/bin/kb ...` is the worktree's board whatever `KEEL_HOME` says.
- **The live board is the live checkout's `kb`, by absolute path**, which is what the card
  block in the brief hands the house and what the brief's scratch section says. That path is
  unchanged, by the same rule read the other way: that `kb`'s package IS the live checkout's,
  so it opens the live board even when it is run from inside a worktree.
- **`keel/prompts.py` adds the recipe** for a scratch deck and a scratch voice gateway, and
  only for a card whose repo is Keel itself (`house.on_keel_itself`): a worktree of any other
  repo has no Keel config to be caught by, so the section would describe nothing.
- **A scratch config reaches nothing live over the network either** (E4, c-415). Moving
  `state_dir` did not move three other things the toml or the home directory names, so a
  scratch config drops them too: its deck port is its own (`config.scratch_port`, the live
  port plus 1000, spread by the checkout's path, the same every time), and `keel serve
  --port 8790` from a worktree is refused by `config.guard_port`; and
  `housetier.shared_key` answers nothing (and
  `mint_shared` refuses), because the shared house key lives under the home directory and
  would otherwise let a scratch process into the live house routes with a real credential.
- **The gateway checks before it binds.** It prints the board and the state directory, and
  refuses to start when its own code is a worktree's while the `kb` it would call is the live
  checkout's ([the talker and voice](50-talker-and-voice.md)).

## The record, and the nudge for it

`context.md` is written while the work happens, not at the end, because it is what lets
someone drop in after the worktree is gone. Six headings: Where it stands, What is next,
Why this shape, Open questions, Evidence, PR body; a card that ships a change also opens
with Risk after Evidence (the pipeline's risk step, below). Screenshots go in `assets/` beside it
and are evidence only once the context embeds them as a markdown image pointing at
`assets/<file>`; a file nothing embeds is a file nobody will open.

At the outcome gate the turn-end hook reads `context.md` once and sends the house back if
a section is missing, empty, or Evidence names no artifact. `options.record_nudged` makes
that once and once only.

## The pre-gate pipeline, and the review core it runs

Every repo house in both spaces runs the same four steps before its outcome gate, in the
order below (a space with `preship_first` runs them in another, see "Preship first"), each
held by a mechanism rather than a sentence (decisions N4, E-9, HP-1 to HP-6;
`keel/review/`). It applies to a repo card in a space whose `house_review` is on
(`[spaces.<name>] house_review`, ON for both spaces since 2026-09-24): never to an errand
or an ask card (no diff), a research card (nothing ships), or a review card
(`options.review_key` or `kind = review`), so a peer review can never stamp a colleague's
branch. The intent is the card's approved plan and `state/cards/<id>/requirements.md`
(the card's own title and brief, written by Keel at launch): nothing inside a house
derives it again. The brief's section is `keel/review/brief.py`; the words for verify and
preship are the space's own, from the file its `[spaces.<name>] pipeline` names
(`etc/pipeline-personal.md`, `<install>/packs/work/pipeline.md`), each with a `## Verify` and a
`## Preship` section (and, for a space that runs preship first, a `## Publish` one), so the
work tools are named only in the work pack.

| Step | What the house does | What holds it |
|---|---|---|
| Review | ONCE per trip to the user's gate, when the build is done: `bin/keel-review prep`, then the reviewer, then the verifier when there are findings; fix or answer each surviving finding, then a FIX check (a bare `prep --since`, each worktree's reviewed head from the stamp, and the verifier alone on the fixes) instead of another review pass. A second full review only for a fixed high or critical finding, never for the size of the fixes, at most `[spaces.<name>] review_full_rounds` per trip (2 when the space names none, `stamp.FULL_ROUNDS_MAX`; 1 at work, where the fix check confirms a fixed high like any other: c-597) (RD-1; size dropped 2026-09-26). Low findings are left as they are by default (declined "low, left as is", listed in the outcome); a true one-liner rides in a medium fix's check, never a fix check of its own. A fix check refused because a full review is earned names that step (a full prep, no `--since`, then only the reviewer), and so does the Stop hook's send-back after it; a second such refusal at the same full-round count blocks the card (`review-limit`, c-529) | the stamp the harness writes, a head per worktree (a full pass's, or moved to the new heads by a confirmed fix check; whatever session), checked by the Stop hook; `kb stage review` refuses an open pass, a stamp missing a worktree's head, and an unanswered surviving finding |
| Verify | the space's own words: the repo's `[house_tests]` command (`make test-changed` for Keel; else `[tests]`) on the committed change, and a reproduction (personal), the dev stack's own containers (work) | the outcome's Evidence must name an artifact (C26) |
| Preship | rebase onto the base's current head (a conflict it cannot resolve is a block), linters, and the space's own (docs and swagger at work) | `kb stage review` refuses a branch that does not contain the base's head |
| Risk | `## Risk` in the outcome: low, medium or high, and why; name every surviving high or critical finding | the lint's C27; `kb stage review` refuses a level below Keel's or a missing id |

### Preship first (c-597, the work space)

A space with `[spaces.<name>] preship_first = true` (work, since c-597: "speed first, nothing
weaker") gets the same four steps in the order that keeps its stamp good and its waiting
short (`brief.PRESHIP_FIRST`):

1. **Preship** first: `git fetch origin`, the rebase, the space's words (docs and swagger at
   work), the linters, one commit; then the space's `## Publish` words (at work, the push and
   the DRAFT pull request, so the code host's CI runs beside the rest). From here the head is
   fixed: a commit while the review pass is open would leave it judging a head that does not
   ship, and before c-597 the docs and swagger commits after the review were what staled the
   stamp and sent a card back to building.
2. **Verify, in the background**: the slow runs (at work the full test container, the
   screenshots, a preview) as background jobs on that head. A turn that ends while one is
   still running is a wait, not a stop: the Stop hook records `waiting_on_background` and
   never nudges it, and the drain only notes the job once ([the drain](30-drain.md), "A
   house idle with a background job of its own").
3. **Review, while they run**: the same pass, then one batch of fixes (the linters run
   again on the fixed head, and the docs for any endpoint a fix touched, before they are
   committed) and ONE fix check, with the space's one full test run on the fixed head
   beside it.
4. **Risk**, as before.

The build before it runs a targeted test only, so the full suite runs once per trip, on the
head that ships. Every check the serial order runs still runs; only the waiting changed. The
Stop hook and the stamp are unchanged: a clean rebase during the review keeps the stamp
(same patch id), and a push changes no head.

**The order is a mechanism, not prose** (c-604: in the sandbox no house did preship first,
the push and the draft came last and nobody ran `keel check`). In such a space `kb stage
review` on a card started with the pipeline (`stagecheck.preship_first_check`, from
`plangate.contract_checks`, on the house's machine) is refused unless (a) the card's draft
pull request was recorded (the `set` event writing `options.pr` or `options.prs`, which the
adapter's `pr` writes and which needs the branch pushed) no later than this trip's NEWEST
closed full review pass (so a house that reviewed too early recovers by pushing, drafting and
reviewing again) (its `at` in the rounds; the trip starts at the newest move to
building that is not the Stop hook's), and (b) the review stamp, the receipt `keel check`
leads to, covers HEAD of every worktree (`gate.covers`). Each refusal names what to run:
(a) the push, the draft, then a full prep, the reviewer and the verifier; (b) `keel check
<id>` and the one step it names. Neither runs a test.

A house briefed at shipping (c-600, `house.at_shipping`) gets the serial order even in such a
space: its push and the draft are refused there, and only the user's Ship sends them. The space's full-pass limit reaches the stamp hook on
its command line (`keel-review-stamp <card> --full-max N`, from `review_full_rounds` at
launch), so a hook that cannot read the board never falls back to another limit; a
`review_full_rounds` below 1 is refused when the config loads.

### The review core

ONE core serves self review (a house's own change) and peer review (a review card, lane RC,
"Peer mode" below):

- **Two agents**, defined per session by `--agents` on every start, resume and rotation
  (`keel/review/agents.py`): `keel-reviewer` and `keel-verifier`, each with Read, Grep and
  Glob and nothing else, on the house's own model (`"model": "inherit"`). A subagent starts
  with a fresh context, so neither sees the house's conversation. The reviewer's stance is
  "this change is broken somewhere; find where", and its checks run in one order: spec,
  correctness and edges, repo standards, test quality (tautological, implementation-coupled,
  horizontally sliced, untested risk paths), safety and security, performance and N+1,
  backward compatibility and migrations, docs drift, writing rules. Spec and standards
  findings are two groups, never reranked against each other. The verifier tries to refute
  each finding against the code.
- **One finding schema** (`keel/review/findings.py`): id, axis (spec or standards),
  severity (critical, high, medium, low), path, line, claim, evidence, suggestion, the
  verdict (kept, unverified, disputed, refuted) with its reason and evidence, and a
  `public_comment` slot that peer mode will fill. The verifier's rules are code there
  (`apply_verdicts`), whatever it answers: a refutation without evidence from the code keeps
  the finding (unverified), an undecided one is kept, and a high or critical finding it
  refutes is DISPUTED with both sides kept, never dropped.
- **One standards loader** (`keel/review/standards.py`): for each repo the diff touches, the
  checklist sections of that repo's OWN `CLAUDE.md` (headings naming standards, checklist,
  non-negotiable, working here, conventions, with their subsections, fenced `#` lines
  skipped), read at review time and never copied into Keel, plus the test-quality rule every
  repo gets.
- **The risk score** (`keel/review/risk.py`): from the surviving findings and what the
  change touches (a migration, access control or auth, more than one repo). High for a
  surviving high or critical finding or two risky touches; medium for one, or a surviving
  medium; low otherwise.

### The review step, file by file

- **A review pass** is one reviewer call and the verifier on its findings, recorded as one
  entry of `rounds` in `review-findings.json` (the JSON keys `rounds`, `round`, `deltas` and
  the finding ids `r<N>.F<k>` kept their old names; everything a person or a house reads
  says pass, c-581). The PR sense of "round" is the shipping round, a different thing.
- `bin/keel-review prep --dir <card dir> --base <branch> [--worktree <path>]...
  [--worktree-base <path> <branch>]...` (the last, c-772, for a worktree whose base is not
  `--base`: a stacked card's worktree of a repo its parent does not work in) writes
  `state/cards/<id>/review.diff` (the branch against the base's current head, one
  `# repo:` header per worktree), `review-standards.md` and `review-prep.json`: the base,
  and per worktree its root, head, base branch and patch id. The pass takes its heads from
  there, not from the subagent's cwd when it finishes, so a commit made after prep is never
  stamped as reviewed. `prep --since` (a fix check) also writes `review-since.diff`: bare,
  each worktree's since is the stamp's head for it; a sha is used where it is a commit and
  the stamp elsewhere (`prep.since_per_root`); a worktree with neither is refused, with the
  full prep to run. On c-272 one sha served two repos and the second had no such commit.
- The house calls the reviewer with ONLY the diff, the plan, the requirements and the
  standards, then the verifier with ONLY `review-findings.json` and the diff.
- **The harness records both answers, not the house.** Two `SubagentStop` hooks, one per
  agent by matcher (`bin/keel-review-stamp`, `keel/review/stamp.py`; Bosun's session has them
  too, as `--bosun`, [Bosun](96-bosun.md) "Its review, once per stack"), read the payload's
  `last_assistant_message` (probed 2026-09-23 on 2.1.280: the payload carries `agent_type`,
  `cwd`, `session_id` and `last_assistant_message`, and the matcher selects the agent
  type). The reviewer's answer opens a new pass in `review-findings.json` (`heads`, `patch_ids`
  and `bases` by worktree root as prep saw them, `head` for the house's own worktree,
  session, base, the findings, the risk); an answer outside the schema is a pass that
  counts for nothing. A pass is closed with no findings or once verified, and then
  `review-stamp.json` names the heads reviewed (`heads` by root, and `head` for old
  readers), with `tests`: the house's own run at that HEAD
  on a clean tree (`targeted`, `core` for `make test-core`, `core-reached` for `make test`, or
  `full`, and its exit), or `none` (`keel/review/testrun.py`,
  c-544). `review.md` is rendered from the JSON on every write, newest pass first (`## Pass N`), with the
  house's answers, and ends with the stamp's line on the tests.
- The house answers a finding with `bin/keel-review answer --dir <card dir> <id> --did
  fixed|declined --why "..."` (`review-answers.json`); it never edits `review.md`. The
  editing tools are denied the stamp and the findings file in the settings.
- **The verifier closes an open pass before anything else** (c-581, r-28 item 3). A
  verifier that finishes while the newest pass is open verifies THAT pass (same session),
  whatever `prep` wrote since; only when the newest pass is closed and prep recorded a
  `since` is it a fix check, recorded on that newest pass and never an older one
  (`stamp.stamp`, `stamp.delta_checked`). An unparsed newest pass takes neither. On c-272
  the house opened pass 6, ran `prep --since` and the verifier: the verdicts landed on
  pass 5 as a fix check, the stamp moved to a head nobody verified, `answer` refused every
  r6 id and `kb stage review` read pass 5. `keel-review answer` and `draft` now read the
  newest pass and refuse an open or unparsed one with its step (`prep.newest_pass`).
- **A fix check that earns a full review says so, and cannot loop** (c-529). Its refusal
  (`stamp.earned_why`) names the step: commit, a FULL `prep` with no `--since`, then only the
  reviewer. `review.md` shows each pass's newest fix check, and the Stop hook's send-back
  after such a refusal carries that sentence rather than its usual "prep --since" advice
  (that advice sent one house round six refused fix checks, 324 to 424 lines each, c-522).
  Each fix check record keeps the `full_rounds` count it was judged at, and once one is earned at
  a count every later fix check on that pass at that count is refused too (a smaller delta from
  a newer `--since` does not undo it). The send-back stops naming the reviewer once a newer
  pass has started, and says to finish that pass instead (the verifier on its findings, or
  the reviewer again when an earlier session started it, since only that session can finish it). A second earned refusal
  at the same count on the same pass blocks the card from the `SubagentStop` hook
  (`stamp.block_loop`, mark `review-limit`). A record
  written before the count was kept never counts. The same hook clears that block once the
  review it asked for is done: when it writes the stamp (a full pass closed, or a fix check
  that moved it) and the card's newest block carries the `review-limit` mark with the words
  it is still blocked with, it unblocks as `hook` with `expect` (`stamp.clear_limit`, c-538;
  c-524 read blocked while building for minutes after its earned full review). The Stop
  hook's own `review-limit` block (no stamp after two asks) clears the same way. The user's block,
  a house's question, or any block after it is never touched.
- Outside Keel (the standalone skill, which has no `--agents` and no hook) the same core is
  two more commands: `keel-review prompt reviewer|verifier` prints an agent's prompt for a
  fresh-context subagent, and `keel-review record --dir <dir> --agent reviewer|verifier
  --answer-file <file>` records its answer exactly as the hook would.
- **The Stop hook holds it**, and only a session that was started with the agents
  (`options.review_session`, recorded at launch, resume and rotation): for a card at review,
  a stamp that does not cover HEAD of every worktree of the card (`gate.covers` over
  `gate.card_heads`, the roots `planlint.card_roots` names) sends the card back to `building` with
  the reason, twice (`options.review_asked`); the third time the card is blocked for the user,
  at review. The same change on a newer base passes: a stamp whose patch id matches the
  branch's change against the base's head now is a review of this change, per worktree, so a
  clean rebase in preship costs no second review, and any real commit in any repo does. A
  stamp written before c-581 has one `head` and no `heads`: `stamp.heads_of` reads it as
  covering the one worktree that has that commit, so a one-repo card in flight is not
  refused, and a second repo it never named is not covered.

### Peer mode: a review card (lane RC)

A review card (`options.review_key`, `kind = review`) reads a colleague's pull request, and
runs the SAME core with nothing that makes a self review a gate (`gate.peer_wanted`, HP-8):

- **The agents** are given (`house.reviewer_of`), on every start and resume, whatever the
  space's `house_review` says.
- **The rounds are the harness's** as before: the same two `SubagentStop` groups, whose
  command carries `--peer` (`keel-review-stamp <card> --peer`), record each answer in
  `review-findings.json` and render `review.md`, and the editing tools are denied those
  files. **No stamp is ever written** (`stamp.stamp(..., peer=True)`), the Stop hook never
  holds the card (`gate.wanted` is false for it), and the record nudge leaves it alone
  (`ending.record_check`): its record is the review kind, which the lint holds.
- **The brief's section** is `brief.peer_block`: prepare (`keel-review prep`, with
  `--since <head>` on a re-review, which also writes `review-since.diff`), the reviewer
  with only the diff, `requirements.md` (the card's title and brief, which the fetcher
  filled from the pull request's title and description) and the standards (plus, on a
  re-review, the change since and `review-ledger.md`, rendered from
  `options.review_posted`; and, when the user's Review settings gave one, the user's focus note,
  `review-focus.md`, rendered from `options.review_focus` by `brief.write_focus` and quoted
  in the brief: where to look hardest, never a narrower review), the verifier, then a
  drafted comment per surviving finding:
  `keel-review draft --dir <card dir> <id> --comment "..."` fills the finding's
  `public_comment` and refuses an empty comment, an em-dash, a refuted finding and one
  with no line to post at.
- **At `kb stage review`** the lint reads the review kind (`keel/planreview.py`, C28 to
  C31) with what `keel/review/ledger.py` knows beyond the file: the core must have a
  complete round for the worktree's HEAD, every surviving finding must be a ```finding
  block (lane FC), and on a re-review a finding may not sit where a finding the user posted or dropped sits, on lines that did
  not change since the head the user reviewed (`git diff -U0 <head>..HEAD` moves each line).

### A feature card: one story's pull requests as one change (lane GRP, GR-2)

A feature card (`options.review_members`, filed by the fetcher for two or more pull
requests of one story, [the drain](30-drain.md)) is a review card with several pull
requests, and the core runs on all of them at once:

- **The worktrees**: one per member, primary first, the rest `--add-dir`s (the work
  adapter, `options.review_worktrees` and `options.review_heads` by label).
- **The agents** (`house.reviewer_of`, `agents.agents_json(members, cross_repo)`): the
  reviewer is told the members and that every finding carries `member`, the label of the
  pull request its line is in; when the members span more than one repo it also runs a
  tenth check, the CROSS-REPO CONTRACT (paths and methods, field names, types and casing,
  status codes and error bodies, access checks against gating, one side changed without
  the other), whose findings have axis `contract` (`findings.AXES`; `review.md` groups
  them under "Cross-repo contract"). A single review's agents are unchanged.
- **Prepare**: ONE `keel-review prep --member <label> <worktree> <base>` per member writes
  one `review.diff` with a `# repo: <repo> member <label>` header each, and the standards
  file gains the contract section when more than one repo is touched
  (`standards.CONTRACT`). `brief.peer_block` hands such a card `feature_block`, and
  `review-ledger.md` also carries what the user answered on a member's own single review before
  it was folded in (`options.review_carried`).
- **The outcome** is the review kind for a feature (`docs/plan-format.md`, "A feature
  card"): one orientation whose board draws the path across the repos, every finding row
  naming its member before its `path:line`, ONE `decision verdict-<repo>-<number>` per
  member. The lint's C32 (`keel/planreview.py`) refuses a row naming no member, a member
  with no verdict or two, and any other decision; the members are the card's
  (`ledger.context` adds them), else the frontmatter's `members:`. A `path:line` resolves in
  any member's worktree (`plangate.AnyResolver`), and C31 matches the member as well as the
  place, each member's ledger lines moved in its own worktree.
- **The user's Approve** (`reviewround.feature_answer`) hands the adapter each member's kept
  comments, head and verdict, one summary naming every member's tally, and the strongest
  verdict (request changes, then comment only, then approve) for the card to show.

### The checks at `kb stage review`

`keel/review/stagecheck.py`, run by `keel/plangate.py` before
the move is written, for a card started with the pipeline, and only once its card
directory shows the review step ran (so a card that never prepared costs no read of the
card). It refuses, each time with the fix: an open or
unparsed newest review pass (its step: the verifier, or the reviewer again); no stamp, or a
stamp with no head for a worktree the card has or the last prep saw (the full prep naming
every `--worktree`, c-581); a branch that
does not contain its base's current head (`options.base`, else the repo's integration
branch once anything has landed on it, `next` for Keel (`merging.integration_ref`, c-526), else the branch the repo's main
checkout has out, fetched first where there is an origin); a surviving finding of the
newest pass that is neither fixed nor answered; a surviving high or critical
finding the outcome does not name by its id; and an outcome Risk lower than Keel's.

**What the user accepted in turning it on** (lane E review finding 6, E-9): the stamp is written
by the harness's hook, but a repo house has an unrestricted Bash running as the same user,
so it could write that file itself. The review is a real step a house is held to, with a
stamp a determined house could still forge; the stamp living where the house cannot write
(on the board, through a credential the house does not hold) is what would make it proof.

## Ending a turn

A house ends its turn at `planning` (attended, waiting), at `review`, or blocked. If it
stops at `building` without one of those, `kb stop-check` answers
`{"decision": "block", "reason": ...}`, which Claude Code feeds back so the session
continues its own turn. That is the old nudge with zero latency and no terminal, at most
twice. The third stop at `building` sets `blocked_reason` and stops nudging, so the deck
shows it.

**The user's tap waiting for the turn to end goes first** (c-604). While a relay of the user's (a
`resume` or `stop`) waits for this house, `kb stop-check`'s nudge and the turn-end news
yield, and nothing else does: the turn ends, and its kick carries the user's tap ([the
drain](30-drain.md), "The user's held tap wins the Stop").

**A Stop with running background tasks is a wait, not a stop.** A house that ends its turn
while a review subagent is still running spends no nudge budget. That was learned live,
after a house was blocked three times while alive and busy.

**A tracking card's house may stop.** A card with children has no stage of its own to move
and `kb stage` refuses it, so there is nothing a nudge could ask for: `kb stop-check`
records the Stop and lets the turn end. Otherwise such a house spends its whole budget being sent back at
`building` once it is a tracking card (c-292).

If a house genuinely cannot continue, `kb block $KEEL_CARD "<what it needs>"` and end the
turn. A decision that changes what the remaining work IS, rather than merely whether it
proceeds, is the one legitimate reason.

## What it may and may not do

- Act only inside its worktree or `$KEEL_CARD_DIR/`. Never the live checkout,
  never another worktree, never a shared running service. The space's brief names the
  isolated tools it uses instead.
- Fan out with fresh subagents (`Explore`, `general-purpose`), never `fork`. The harness is
  started with `--disallowed-tools "Agent(fork)"`, so this one is a mechanism.
- Never approve its own gates: `kb approve` refuses without the deck's human token, which
  a house does not hold.
- Never end a session, its own or another's.
- File a follow-up, or work someone else will do, with `kb create --from $KEEL_CARD`: it
  records where the card came from and leaves this card's stage and gates alone. Split this
  card's OWN work with `kb split $KEEL_CARD --slice ...` at the plan gate, which makes this
  card a tracking card with no gate of its own; `kb create --parent` is refused here. A
  card that must change code carries `--repo <name>`. See
  [cards and gates](10-cards-and-gates.md).

## Where a house runs, and with what

Four placements, one table. `house.placement` decides it from the card alone: a card with
a `repo` is a repo card, a card whose `repo` is not one the config lists is a project card,
a card without a `repo` is an errand, and an errand the fetch role made from a segment's
asks is an ask card ([segments](70-segments-and-fetch.md)).

| The card | Where it runs | Its tools | How it finishes |
|---|---|---|---|
| Repo card | its own worktree, further repos as `--add-dir`s | the full set, `--restricted` off | `kb stage $KEEL_CARD review --output <ref>` |
| New project (a `repo` the config does not list) | a worktree cut from `<projects_dir>/<name>`, which placement opens when the card says to | the same | the same, and Approve outcome merges into that project's `main` |
| Errand (no repo) | `state/cards/<id>/`, plus what the card opened and the Atlas | `house.ERRAND_TOOLS`, with Bash fenced to the board and the web read-only | the same, through its fenced `kb` |
| Ask card (`options.drop`) | the same, plus the segment directory | the worker's `options.tools`, often no Bash at all | it writes the drop; the Stop hook files the card |

A fork's review card (c-730 r1.F1, r2.F1, r2.F3: a review card with `options.review_fork`,
which the drain sets from a pack row marked `fork`; `house.is_fork_review`) reviews code from
outside the team, so its house reads that code and never runs it:

- it is confined (`--restricted`) in the fork's checkout, its card directory and the Atlas
  added (`house.placement`), with `house.FORK_REVIEW_TOOLS` (`Read,Write,Edit,Glob,Grep,Bash,Agent`:
  no web);
- its Bash runs behind the board fence given `--review` (`bin/keel-board-fence`): the board,
  and Keel's two review steps by absolute path, `bin/keel-review prep` and `draft`, and nothing
  of the fork's, no build, test or script; the brief says so (`prompts.FORK_REVIEW`). The two
  steps are pinned (`house.fork_review_pins`: `--card-dir <state/cards/id> --worktree
  <checkout>` on the hook): every `--dir` must be the card's own directory and every
  `--worktree` its checkout, as absolute paths. Only `--dir`, `--base`, `--worktree`,
  `--since` and `--comment` pass, each written in full, and every other word that starts
  with a dash is refused (`--remote`, `--member`, `--twin`, and a shortened `--d`), while
  `keel-review`'s parsers expand no shortened flag (`allow_abbrev=False`), so a hijacked
  house cannot point the steps at another card or repo;
- it loads `--setting-sources user` (`house.setting_sources`, `harness.session_flags`): the
  user's settings and Keel's `--settings` apply, the fork's project and local settings and
  their hooks never do. `claude --help` (2.1.295) does not say whether the repo's CLAUDE.md is
  read under it, and that was not probed.

Every other review card, the work pack's and a GitHub one from the repository itself, starts
exactly as it did before c-730. Every door into a card's house takes these flags from ONE
helper, `house.harness_flags(house.placement(...))`: the start (`house.launch`), the resume
(`house.resume`), the rotation's fresh start (`rotate.start_fresh`), and the one-shot turn,
the streamed turn and the kept-alive conversation (through `housetalk.plan` and `flags_of`),
so no door can leave one out.

An errand runs `--restricted` with `ERRAND_TOOLS`
(`Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch`) unless `options.tools` names the
tools. The web is there in both spaces because neither tool carries a credential, so the
space boundary does not move, and because a research errand without it can only report
that it knows nothing (c-291, whose house could only write that it had no web tool and so
knew nothing of what it was asked). An ask card keeps its worker's `options.tools` as written; a worker
that wants the web lists it. The brief's `### The web` section comes from
`prompts.web_block`, read off the same list `--tools` gets, so it appears exactly when the
tools do.

### What a confined house may open, and may write

`--restricted` confines the file tools to the cwd and the `--add-dir`s, so the add-dirs are
the whole of what a confined house can reach. `house.restricted_add_dirs` assembles them
from the same options the brief was written from, resolved and de-duplicated so one
directory is never handed over twice under two spellings:

- `options.add_dirs`, which is how an ask card reaches its segment's own `data/`;
- the segment `options.segment` names, and the directory `options.drop` belongs in, so a
  card that is reasoning about a segment can open the files it is reasoning about;
- `docs/atlas`, because the brief tells every house to read it and a brief may not name
  what the tool set denies.

A directory that is not there is left out: `--add-dir` refuses a path that does not exist,
and a refused flag is a house that never starts.

Every house is also denied its editing tools on the CLAUDE.md of every space and of each
repo the install copied into one, and Bash on a command that spells one of those absolute
paths (`house.tier_deny`, c-678 review): Keel runs lines out of those files, and only from
the text the user adopted or saved ([onboarding](89-onboarding.md)). The rules stop the
plain attempt only; what holds is that a changed file runs none of its own lines and, where
Keel lands the work and the test command would have come from that file, refuses the
landing. A test command the config names (`[house_tests]`, `[tests]`) is handed to the
house as before, whatever the file's standing (`house.house_tests`); only where the landing
will be refused does the brief add that no test run counts as a pass.

The Atlas is opened for READING only, and that is a mechanism rather than a request.
`--add-dir` grants writes under `--permission-mode auto`, so `house.atlas_deny` puts
`Edit`, `Write`, `MultiEdit` and `NotebookEdit` on that path into the settings file's
`permissions.deny`, where a deny beats every allow. The rule carries a DOUBLE leading
slash (`Edit(//Users/...)`): one slash anchors the pattern at the settings file instead of
the filesystem root, so a single-slash rule would match nothing and fail open. A confined
house is told the same thing in words, so it does not learn it one refusal at a time.

### Every house runs without the background worktree guard, and cannot enter a worktree

Claude Code refuses a background session's `Edit` and `Write` inside a git repository until
the session calls `EnterWorktree`. Every house already runs where it works: a repo card in
the worktree `placement` cut for it, a confined house in `state/cards/<id>/`, inside the
Keel repo, whose plan, context and drop all belong there. So `house.settings_body` writes
`worktree.bgIsolation = "none"` into the settings file of EVERY house (work, personal and
confined alike), and puts `EnterWorktree` and `ExitWorktree` (`house.WORKTREE_DENY`) into
its `permissions.deny`, so the tools do not exist for it.

Without the first (c-271), a house that has finished its investigation cannot save
`plan.md` in its own card directory, writes the whole plan into a `kb note` instead and
blocks itself asking for card-dir writes. Without the second (c-605), a
repo house told to build may call `EnterWorktree` and sit on its permission prompt,
which no Answer and no resume can close (the next turn asks again).

The settings file is read when a session starts or resumes, never by a live one (a probe
showed a rewrite does not reach a running session). A house that was already running when
this landed gets the rule at its next resume, which rewrites the file (`house.resume`; a
tell rewrites it too, but the live session it reaches keeps what it started with). One
already stuck on the prompt needs the user's Stop, then their Resume.

### A repo the config does not list

A personal space may carry `projects_dir`. A card whose `repo` is
not one of the space's listed repos, and is a plain directory name (`[a-z0-9][a-z0-9-]*`,
so no slash, no `..`, no leading dot), resolves to `<projects_dir>/<name>`
(`Space.repo_path`). What happens next is `adapters.project_repo`, and only one of its
three answers creates anything:

- the directory is a git repo: it is a repo like any other, discovered rather than listed.
  A worktree is cut from it, the house is unrestricted with the full tool set, and Approve
  outcome merges its branch by the usual personal flow (`keel/merging.py`);
- the directory is not there and the card carries `options.new_project`: `git init -b main`,
  a README naming the card and the date, one commit, then it proceeds as a repo card;
- the directory is not there and the card does not carry the option: a refusal naming the
  card and the flag, so a misspelt repo never scaffolds a project nobody meant to open. A
  directory that exists but is not a git repo is always a refusal.

Every git repo directly under `projects_dir` is addressable by its directory name: that is
the whole discovery rule, and `keel doctor` prints the list. A listed repo always wins, so
a project directory cannot shadow one.

`kb create --new-project <name>` is the one place what such a card IS gets decided: it sets
`repo`, sets `options.new_project`, and defaults `autonomy` to `attended`, because the first
card on an empty repository decides what the project is and that is the user's call. `--autonomy`
still wins when it is given. The deck's card sheet carries the same field
([the deck](40-deck.md)). The brief gains a section naming the path and saying the plan
comes first.

### An errand gets the board, and only the board

The Bash in that list is there for one reason: an errand house is briefed with the board's
whole verb list, and without a shell it can run none of it, so it cannot
investigate a card it is asked about (c-271).

So a confined house that has Bash at all runs behind the **board fence**,
`bin/keel-board-fence`, a `PreToolUse` hook on `Bash` that `house.settings_for` writes for
a card `house.is_fenced` says yes to. It allows ONE plain invocation of `bin/kb`, or of
`bin/keel deck`, named by absolute path, and refuses everything else on stderr with
"this house is confined to the board: kb and keel deck only" and the reason. A chain, a
pipe, a redirect, a backtick, a `$(`, an env-var prefix, a `cd` first, a relative name and
anything it cannot parse are all refused: it fails CLOSED, unlike the machine-wide guard
beside it, which guards a full tool set and so fails open. The fence joins that guard
rather than replacing it, and an unrestricted house has neither hook beyond the guard.

A `worker.md` that lists Bash gets the fence too. One that lists no Bash (the daybook's
`tools: Read,Write`) has nothing to fence and needs none: its finishing step is the Stop
hook's, not a command's.

### A wait loop on pgrep -f is refused

c-526's house ran its final suite as a background job behind
`while pgrep -f tests.parallel; do sleep 5; done`. The loop's own shell carries the pattern
in its command line, so `pgrep -f` always found at least that shell and the loop never
ended: the house idled thirty minutes, and the shell outlived `claude stop` until it was
killed by hand (r-8). It is the same trap as `pkill -f`: a pattern matches the command line
that says it.

So every house with an open shell runs `bin/keel-house-guard`, a `PreToolUse` hook on
`Bash` that `house.hooks_for` adds whether or not the machine has the stack guard (a machine has it when `[machine] stack_guard_hook` names the script,
`house.guard_hooks`). It refuses a command that has a `while` or `until` loop and a `pgrep` carrying
`-f` (alone or in a flag group such as `-af`) or `--full`, and its refusal names the three
ways out: the suite in the foreground, `run_in_background` and its completion notice, or a
wait on a pid it can name (`while kill -0 <pid>`). A plain `pgrep -f` to look is allowed,
which is what `CLAUDE.md` asks before a kill. It fails OPEN on its own error, as the stack
guard does, because it guards a full tool set. A fenced errand does not get it: its fence
already refuses every loop. The hook is the rule, so the contract says nothing about it (c-603).

**A pack may read the command too** (c-689). When the card's space pack ships a `guard` verb
(`[guard]` in its `pack.toml`; the GitHub pack does, the work and sandbox packs do not),
`house.hooks_for` names the verb and the pack's tools after the card id, and the house
guard hands each command to it (`<pack>/guard <card>`, `{"command", "cwd"}` as JSON on
stdin) and refuses with the sentence it answers. That is how a house on the GitHub pack is
held to gh's reads: the pack parses the line, where a permission deny could only match its
text. The order is: first the `pgrep -f` loop, then the pack's guard, then the hook's two push
checks below (shipping, a shared branch), which hold whatever the pack allowed. A pack guard
that errors or gives no answer in four seconds refuses only a command
that names the pack's tool as a word (`gh`) and allows the rest, between the hook's own
fail open and the board fence's fail closed. A pack that shows a guard and does not load
blocks the card at launch, as a failing `deny` verb does. A pack with no `guard` verb
changes nothing: the hook command is the one it always was. The whole hook runs to one
deadline, 17 seconds, under the harness's twenty: the pack, the git reads and the board
share it, and a push it cannot finish checking is refused. [Packs](62-packs.md),
"A pack's guard".

## Stopping a house ends its background jobs

`claude stop` ends the Claude session and deliberately leaves its background shells
running: the harness writes them to `<config dir>/jobs/<short id>/adopt.json` (each shell's
`pid`, its `startTimeTicks` and its `command`) and walks away. c-526's pid 156548 is
recorded there. So every path that stops a house goes through `housejobs.stop`
(`keel/housejobs.py`), which calls `claude stop` and then ends each shell it left:

- **Found by pid, never by pattern.** The pids come from `adopt.json`, and only a record
  written after this stop counts. The stop waits up to ten seconds for it, and only when the
  session's `state.json` said a job was in flight, so an ordinary stop costs nothing.
- **Proven before it is touched.** On Linux the live pid's start ticks (`/proc/<pid>/stat`,
  field 22) must equal the recorded `startTimeTicks`; elsewhere `ps -o lstart` must fall
  within five seconds of the task's `startedAt`. A pid that cannot be proven is left
  running and the note says so, because a reused pid is somebody else's process.
- **The whole job.** The harness starts each background shell as the leader of its own
  process session, so everything it started (the suite, its workers, a `sleep`) shares its
  session id. Every live member gets SIGTERM, then SIGKILL after three seconds.
- **Said on the card.** The stop's note names each job it ended (`ended its background job
  <task> (pid <n>)`) or left.

The callers: `house.retire_session` (a resume's superseded session, Approve outcome's
finished house of a card now done, a rotation's old one), the deck's
Stop (`actions.py`) and its Close idle house (`actions.close_idle_one`), the drain's carried
Stop and carried close (`drain.carry_close_idle`) and its retired tracking session, a
rotation's unrecorded fresh session, and Bosun's Stop, Restart and stuck-row clear.
`tests/test_housejobs.py` fails on any other `harness.stop` call. The one exception is
voice's pause (`housetalk.stop_house`): it hands the session to a conversation and wakes
the SAME session afterwards, so its jobs are live work and are left running.

**One rule for working** (`housejobs.working`, c-535 and r-26): a row is in a turn when the
listing names a process for it (`pid`) and its `state` is `working`; a row with no `state`
falls back to `status: busy`. Never `status` alone: an idle house whose background job still
runs is listed `status: busy`, `state: done` (probed 2026-09-26). Never a row with no
process: c-561's superseded session 735f0cab stayed listed `state: working` with no
`status` and no `pid` for two days (probed 2026-09-29 on 2.1.284), and every landing behind
it was refused while Bosun's read said "not running". Every reader asks this one function:
resume (`house.refuse_if_busy`), the landing worker's `finish_house` and guard, the drain's
relayed finished house and the deck (`row_facts` carries
`working`, which `houseBusy` reads). So an idle house with a leftover job is resumed,
superseded and stopped like any idle one, and the stop ends its jobs (`housejobs.stop`):
a job the conversation could no longer hear from anyway, since its completion notice would
go to the session being stopped. A refusal names the row in the harness's words
(`housejobs.row_said`: bg id, session, state, status, pid). A row listed as working with no
process (`housejobs.ghost`) is a `keel doctor` problem naming its card (`keel/ghosts.py`).
The one question it does not answer is "is it doing anything", which reads `busy`: the
pool (`drain.working_now`, `deckstate.busy_house`), a rotation waiting out its checkpoint
turn (`rotate.py`'s finish), since a house idle on a
background job of its own (its tests running) is still doing something, and nothing
automatic stops that.

**An idle house with a job running says so.** While a session lives, its `state.json`
counts what is in flight (`inFlight.tasks`) and lists each task in `fan` (`id`, `label`,
`startedAt`). A house the harness lists outside a turn (its `state` is not `working`; its `status` says busy while the job runs, probed 2026-09-26) with a shell in that list is waiting on
a job of its own: the deck's house word says `idle · job running` (`deckstate.jobs_of`, the
card's `jobs`), and the drain notes it on the card once per job (`drain.jobs_upkeep`,
[the drain](30-drain.md)).

## Closing an idle house (c-607)

A house listed idle still holds its memory: the `claude` process and everything under it (its
MCP servers, its tools). The deck shows that these houses are
live and taking memory, most of all one at review that someone has left, so a user
who is not going to review now can close it, and it picks up again with a
5 to 15 second delay.

**What it holds** (`keel/housemem.py`): the RSS of the pid the harness lists for the session
(`claude agents --json`, the row's `pid`) plus every process under it by parent pid, read on
the house's own machine: `/proc/<pid>/stat` and `statm` on Linux, one `ps -A -o
pid=,ppid=,rss=` on macOS, one table per two seconds whoever asks (`housemem.CACHE_SECONDS`),
with a background job counted by the pid its job record names when it names one (a shell
reparented to pid 1 is no longer under the house). It is `mem_mb` in the live strip's facts
(rounded to 50 MB, so a small wobble is not news), read by the deck's `Watcher` while a stream is open and held in memory only, never on the board. A
row with no `pid` has no reading and the deck shows none.

**Close idle house** (`house.close_idle`, `keel/idleclose.py`) is a human stop, like Stop
session, offered only at review and shipping (where the user's gate answer, or the next batch,
brings the house back by itself; at planning and building nothing would, so Stop session is
the user's way there, c-607 review), and only ever of an idle house: the deck draws it only while the harness lists the
house out of a turn, and the rule (`idleclose.not_idle`) is checked again where the tap
lands and once more by
the drain when it carries the relay: a house that is working, has a background
job of its own running, is open in a terminal, is held by voice or a drop-in, has a tap of the user's
pending, or is being TOLD something is refused with the reason. Every close (the user's tap, the drain carrying it, both of the drain's own ends below) goes through
`idleclose.close_here`, which reads the card and a fresh listing, asks `not_idle` and stops
the house UNDER THE CARD'S LOCK (`house.card_lock`). A tell holds the same lock for its
decision and, before its 7 to 17 s send, marks itself in flight beside its told file
(`state/cards/<id>/told/sending`, `tellhouse.telling`, cleared when the send ends, not
believed after two minutes), since its turn start is recorded only after the send. So a close
and a tell serialize: the close sees the tell in flight and refuses, or closes first and the
tell resumes the exited house (c-607 review).
Its note is marked `closed-idle`, NOT `human-stop`, and the difference is what happens next:

| | Stop session (`human-stop`, c-605) | Close idle house (`closed-idle`, c-607) |
|---|---|---|
| the drain's resume of an exited house | passes it over | passes it over |
| the next review batch at shipping | waits for the user's Resume, noted once | resumes it (`claude --resume`) |
| the user's gate answer or Resume | resumes it | resumes it |

Resuming takes about 5 to 15 s, the conversation kept. The drain carries the user's relayed tap,
and ends an idle house of its own accord in exactly three cases, two decided with the user on ask
a-72 and one on the user's explicit word for re-offered batches (c-651) (`keel/shipidle.py`,
`drain.idle_upkeep`), each only on a house the harness lists idle and
checked again on a fresh listing right before the stop, never a working one:

- **A merge made the card done** (`shipping.merged`): its idle house is ended, final
  (`merged-end` on the note; a done card is never resumed), by the same `not_idle` (a job of
  its own, a pending tap or a drop-in leaves it too). A house still working is left,
  and a later pass ends it once it is idle, found again by the card's own record (done, its
  shipping record's `facts` state `merged`, c-793, its session still listed).
- **A shipping house idle over two hours** by the board's own record of its turn ending
  (the current session's newest `Stop` hook with no turn since, `views.turn_ended`, a Stop
  the hook blocked not counting since the turn went on; never quiet time) that has no background job of its own running: closed with `closed-idle`, so
  its next review batch, the user's gate answer or Resume brings it back. The card and Now say
  it ahead, `idle 1h40m, closes at 2h` (`derived.ship_idle`).
- **A shipping house whose turn on its re-offered batch has ended** (c-651,
  `keel/shipreoffer.py`):
  the newest batch is the one `kb ship <id> reoffer` asked for, and by the board's order of
  events its own turn (the first turn start after the tell) has had its first `Stop`, with
  no turn started since. Closed at once with `closed-idle`, and only once, the rule being
  that idle houses must not hold memory; its next review batch resumes it. Once any later
  turn has started (the user's Talk, Resume, voice or Drop in) the re-offer is over and
  closes nothing. The card and Now say it ahead: `idle 4m, closes now (its turn on the re-offer ended)`
  (`derived.ship_idle.reoffer`). A normal batch keeps the two hours. A turn that ended is
  not an answer (c-654): the close's note says the turn ended and how many of the batch's
  items were left with no verdict, and with any the card is blocked for the user with them named
  ([the drain](30-drain.md), "Idle houses at shipping and after a merge"). The user's own
  send-back at shipping (`kb ship <id> sendback`, c-663) adds no end of a house: its item
  is an ordinary one of the batch and writes no hand-over mark, which is the only thing
  this close hangs off, so its house is kept by the two hours above.

## What the deck sees of a working house

Nothing a house does is reported to Keel by the house: the deck draws a working house from
what the harness writes about it. Its agents row says whether it is in a turn, its job record
(`<config dir>/jobs/<short id>/state.json`) says in the harness's own words what it is doing
and which subagents and shells it has running, and its transcript says its last tool, its
todo list and when its turn began (`keel/livetail.py`). The deck's live strip reads these on
the house's own machine only while the user is watching, and shows them as facts with ages
([the deck](40-deck.md), "The live strip"); a Notification hook the house fires (a
permission prompt) shows on its card the moment it lands on the board. A house is never
asked to report its own progress, and nothing reads a terminal.

## Drop in

Drop in hands out the command that enters a house ([the deck](40-deck.md), `keel/dropin.py`):
`claude attach` for a live one, `claude --resume` for one that has exited. The command is
for this machine and is handed out as it is, with no ssh wrap. An exited house whose
conversation the harness no longer holds is started afresh from the card's record first,
and the command joins the new session by its own id, or nothing is handed out; on a done
card it is refused in plain words ("Resume and block", below, c-654).

**An exited house the user resumes this way is held while the user is in it** (U3). Probed on 2.1.281
(`tests/fixtures/harness/README.md`, "Drop in on an exited house"): a terminal
`claude --resume <uuid>` keeps the session id and is listed as `kind: interactive`, it
carries none of the house's hooks, and Keel's own `claude --resume <uuid> --bg ...` on it
starts a COPY while the supersede's `claude stop` misses the user's terminal. So Drop in on an
exited house takes `options.dropin_hold` (`dropin.hold_record`: the session and a fifteen
minute `until` to paste in), as the user through the deck's `kb`; only the user and the drain may
write it and no card is filed with one. While it holds, every resume is refused (below),
and the drain leaves the card alone ([the drain](30-drain.md)). It ends when nobody joined
before `until`, or, once the drain has seen the user's session listed, when that session leaves
the listing, whatever `until` says. A live house needs none of this: `claude attach` joins
the one session. The sheet's sentence for the resume case says Keel keeps off it.
A session the listing ALREADY gives as `kind: interactive` gets no command at all
(`dropin.AlreadyOpen`): `claude attach` takes a background session's id, and a second
`--resume` would fork it, so the answer is "already open in a terminal, carry on there".

## A card that changes under a live house

A house reads its card once, in the brief's card block. c-530 was started attended and set
autonomous 18 seconds later; its house would have waited at planning with nothing showing
it needed the user. So `keel/briefnews.py` treats the block in `state/cards/<id>/brief.md` as
the record of what the house was TOLD, and the difference between it and the card now as
news (c-533). No second record: a brief with no readable block is no news.

- **Briefed fields** are title, brief, autonomy, repo, model, and `options.base`,
  `options.browser`. Stage and plan_ref are the house's own moves, and
  the rest of `options` is Keel's bookkeeping, so neither is news. Nor is a field whose
  last `set` was the house's own (`briefnews.own_moves`): a house retitles its card after
  the user's redirect, and already knows.
- **At a turn end** (`ending.with_news`), a Stop at planning or building on an unblocked,
  unrotated card answers `block` with the news as its reason, notes it on the card, then
  rewrites the block (in that order, so a failure leaves the news pending). The harness
  sends the same live session back for one more turn; nothing is ended. A voice hold or a running background
  task defers it like the other rules, and any other stage leaves it pending.
- **On a resume** (`house.resume_card`), the news is appended to the prompt, whoever
  resumes, and the block is rewritten once the resume took. A house idle at a gate hears it
  this way, with the user's answer.
- Autonomy carries one line of what it means for the house, and a model change says it
  takes effect at the next resume, which is when `--model` applies.

## Resume and block

Every house starts with `--remote-control <card id>` as well, so the same session is open
in the Claude app; the drain reads the link out of the session's log a few seconds after
start and keeps it as `options.app_link`, which is the inspector's "Open in Claude app"
button. A resume mints a new link with its new session, so the link is re-read then too.
A resume that KEEPS its session reads no link. The link of a kept session with none on
record is read from the log on the user's **Open in Claude app** tap (`house.open_app`,
`openapp.open_for_app`), also for a house in its turn, which is neither woken nor refused:
nothing is started (c-653).

`house.resume` runs `claude --resume <session_id> --bg` with the settings file rewritten
from the current code (the hooks and the confinement are Keel's, so a card already open is
resumed under today's, the same reason the theme is copied again), so the resumed house
keeps its name, model and confinement. The conversation continues but
the harness mints a NEW session uuid, which `house.resume` records on the card, and leaves
the old process idle; the resume then stops that superseded session if the harness still
lists it, and notes it on the card. That is the one stop Keel performs on its own, and it
ends no work: the conversation continued in the new session. The deck's Resume house
button is this; so is the drain's one automatic resume ([the drain](30-drain.md)).

**A conversation the harness no longer holds is not resumed: the house starts afresh**
(c-654, `keel/afresh.py`). The harness keeps a transcript for its retention period only
(30 days by default). A shipping house last used longer ago than that
(c-015, c-017, c-037) and resumed for a review batch shows it: `claude --resume <id> --bg` prints
its `backgrounded` line with the SAME id and exits 0, a `SessionEnd` hook (reason `other`)
comes four seconds later and nothing else, and the card sits at "judging 1" with nothing on
it to say why (`claude agents --json --all` lists such a session `failed`; the plain listing
does not list it). The launch cannot say a conversation is gone, so a resume asks first
(`harness.conversation_gone`, from `house.resume_card`, which every resume comes through: a
review batch, the user's Resume, a gate answer, the drain's own resume, a landing's merge, a
repair): `claude -p --resume <id>` with NO prompt, which exits 1 saying `No conversation
found with session ID: <id>` for one that is gone, and `No deferred tool marker found in
the resumed session ... Provide a prompt to continue the conversation` for one that is
there (probed on 2.1.289, about 1.6 s, no model call). Only the harness's own "No
conversation found" counts; a failed call, an expired login, a probe that overran is not a
guess, and the resume goes on as before.

The probe cannot act (c-654 review). Its message says the harness looks for a deferred
tool call to continue from, and a session that ended on one was never probed, so the probe
carries the login probe's flags (`harness.LOGIN_FLAGS`: no tool, no MCP server, nothing
saved, the cheapest model), runs in its own process group and is killed whole after 15
seconds (`harness.run_alone`), so a `claude` that hangs never holds the card's lock. A
short id a card kept (the listing never showed its row) is no session id to `-p --resume`,
so it is resolved to its uuid through `claude agents --json --all` first, and one that
listing does not hold is never asked (`harness.full_session`).

**One answer of the harness never replaces a session** (c-654 review). Replacing a card's
session is not undone, so a house starts afresh only when ALL of these hold
(`afresh.wanted`):

1. **The harness lists no live process for the session**, by the row the resume's own busy
   check fetched (`house.refuse_if_busy`). A session with a process is never asked about:
   it has a conversation by being alive, a fresh house beside it would be a twin nothing
   owns, and it is resumed (and the idle one superseded) as ever. With no row at all the
   harness is asked again and strictly (`afresh.no_process`): a listing that failed
   answers an empty one, which is never read as "no process", and the resume goes ahead
   as before.
2. **The harness says the conversation is gone**, asked in the directory the resume itself
   would run in: the resume's placement, the directory Drop in's command enters, the one a
   wake uses.
3. **The board shows no turn the card's house really ran in the last 14 days**
   (`afresh.RECENT_DAYS`): no `Stop` hook and no `Notification`, whichever session id it
   carries. A resume mints a new id, so a session minted yesterday that died before its
   first Stop has no turn of its own, while the card shows the conversation in use the day
   before under the id it had then. Nothing else
   is use. A `resume` or `session` event and a `SessionEnd` are not: the doomed resume of
   a gone conversation writes exactly a resume and then a `SessionEnd` with no `Stop`,
   which is what such a card carries (c-015, c-017, c-037), and it starts afresh at
   its next resume. A transcript is kept 30 days by default, so "gone" two weeks after
   a turn is two facts that disagree, and Keel does not pick one: the card is BLOCKED for
   the user (under its own mark `afresh-withheld`) with both said, how long
   ago the card shows it used and the whole ids of the session and of the one before it,
   so the user can look for them by hand; nothing is started and nothing is stopped.

**At most one fresh start stands unproven.** A house started afresh whose own session never
ran a turn (no `Stop` of it, blocked or not, and no `Notification`), and whose conversation
the harness then says is gone too, is the launch that
dies in its first seconds: a second fresh start is refused and the card blocked with both
sessions named (mark `afresh-twice`). A fresh start spends the drain's once-only automatic resume as any resume
does (`house.auto_resume_spent` reads the note the start leaves), so the next pass blocks
that card ("exited twice") and starts nothing. Before, a fresh start left no mark and a
house that died was started again on every pass.

**Both blocks are the user's, and the user's unblock is the way out of each** (`afresh.answered`).
Neither mark carries `mechanics`, so Bosun's unblock, resume and retry repairs are refused
on them by the rule already there (`repair.refuse_unless_mechanics`); the drain's unblock
is not the user's answer either. Each block's text says it: unblock the card yourself, only your
own unblock counts. Once the user has, the next resume, Drop in or Resume and open in app starts
the house afresh, the first two conditions still required: one start (after the
`afresh-twice` block, exactly one more), for the session the block names (its `session`
in the block's data), never for a later one. The user's answer is durable. A block written on top
that only restates the refusal (it quotes its text) is looked past, and the callers Keel
owns leave the block standing instead of writing one: a review batch goes back to waiting
(`shipping.put_back`), a carried tap and a landing's conflict resume log and stop there
(`drain.carry_resume`, `landing.refused_here`). The drain's own resume of an exited house
takes a card the user has just answered to the fresh start even with its one automatic resume
spent, never to "exited twice" (`afresh.his_word`). The fresh start consumes the answer.

When all three hold, a NEW house is started under the lock the resume holds, by `launch` itself
(`house.launch_here`), so the worktree, the settings and fence, the model and the name are
the ones a resume would use. Its first prompt is the brief, then where the card's own
record of the lost conversation is (`prompts.afresh`: `context.md`, the plan the user approved,
the outcome and its pull request, the branch and its base, the card's directory), then the
prompt the resume would have carried (a review batch, the user's answer, the plain resume). The
card says it in a note ("the old conversation had expired ... a new house was started from
the card's own record") that keeps the old session's WHOLE id, and the id of the session
before it when there was one, so the user can look for them by
hand, and the start is that house's turn start on the board (a `session`
event, no `resume`). Nothing is ended: the old session has no process and no conversation.
A fresh start that fails blocks the card as any start does (`mechanics`), and the error it
raises says both halves (the conversation expired, and why no house started), which a
review batch puts on its own block as it goes back to waiting (`shipping.put_back`).
The record named includes `handoff.md` when a rotation's checkpoint is there.

The user's two ways into a house that pass no prompt ask the same question first, by the same
three conditions (`afresh.here`; c-020 at shipping: its Drop in command failed at the user's terminal
because the session no longer existed). **Drop in** on an exited house would hand out
`claude --resume <id>`: when the conversation is gone, a new house is started first and the
command handed out is `claude attach` for the NEW session, built from the start's own id
(`dropin.joined`), with no hold to take and any hold left from an earlier try cleared
(`actions.dropin_afresh`). A new house the harness does not list yet is not handed out at
all, and never as a resume: it may be in its first turn, and `claude --resume` of it would
start a copy; the user taps again. The second tap holds the same line (`afresh.NotListed`): a
house started afresh that has not run a turn and is still unlisted is not asked about at
all, so it is neither handed out as a resume nor blocked while it starts, from Drop in and
from Resume and open in app alike; Resume house says what became of one that stays
unlisted. Once the user has unblocked the `afresh-twice` block for that house, both taps ask
again and start the one more house. On a DONE card, whose house is never started again, a gone
conversation is refused in plain words, with no command and no hold, from Resume and open in
app. Drop in on a done card (c-787) first remakes its torn-down directory, empty, so the
resume finds the conversation, and when that is gone hands out a fresh session in the card's
record, the user's own terminal's and not a house ([the deck](40-deck.md), "On a done card"). **Resume and open in app**
would wake the session (`claude --resume <id> --bg`, no flags), which fails the same way:
the new house is started instead and its link is the one opened (`keel/openapp.py`). In both
the new house is told the user is about to join it: read the record, say where the card stands,
end the turn, change nothing until the user says (`prompts.JOIN_AFRESH`). Rotation's own fresh
start (`rotate.start_fresh`) is not this path: it swaps the session compare-and-set against
the checkpointing one, which a start under the card's lock does not need, so this reuses
`launch` and the rotation's record (`handoff.md`), not that function. The voice wake
(`house.wake` when a voice conversation ends, and the drain's `release_holds`) does not ask
either, on purpose: voice has just taken a turn in that conversation, so it is there, and
the question would cost every wake a second and a half.

**A resume is REFUSED while the session is working** (`house.refuse_if_busy`, E1 of the
overnight clearance, c-443). A resume passes flags, and `claude --resume --bg` with flags on a
RUNNING session starts a copy; the supersede rule above would then stop the original in the
middle of its turn. So `house.resume` asks `claude agents --json` first and raises
`house.Busy` when the row's `status` is `busy`, whoever asked. Not even the user's gate answer
(`force`) overrides it. Since c-598 the user's taps rarely reach this refusal: an IDLE live house is
TOLD rather than resumed, and the user's tap for a WORKING one is held until its turn ends (below).
Bosun's approval of a working house still only notes it, and the drain's own resume only
ever puts back a house that exited.

**The user's taps, told in place** (c-598, `keel/tellhouse.py`, approved by the user in a-70). The user's
Approve plan, Send back, Ask and Resume reach a house the harness lists as idle as a MESSAGE
into its own session (`relay.tell`, the mechanism Bosun's wake uses, c-530), not a resumed
copy: probed on 2.1.285 (`tests/fixtures/harness/README.md`, c-598), a cross-session message into an
idle `claude --bg` session starts a new turn in the same process, so the session id and the
claude.ai link never move and nothing is stopped. `tellhouse.deliver` does it under the card's
lock. The prompt is written to `state/cards/<id>/told/<stamp>.md` and the message is a
short pointer to that file, sent by name (the card id; the harness takes no id there, and
refuses outright when two live sessions share the name): the c-530 probe found the relay's
model obeying words in a long message instead of sending them. It is recorded as a `resume`
event on the SAME session, so the drain's once-only mark and the quiet rule see a turn start
as they would for a resume; briefed news rides with it and a pending rotation is cancelled,
as a resume does. A house the harness does not list (it exited) or lists with no process,
and a card voice is holding, go the resume path above unchanged. A caller that only tells passes
`exited=REFUSE` (c-718 r1.F4, the stacking step): such a house is refused with
`tellhouse.NotRunning` instead, and so is a tell whose relay certainly failed, which is then
never turned into a resume. A tell that certainly did
not arrive is noted and falls back to the resume; only the relay call is inside that
fallback, so nothing failing after a send can deliver twice. One that MAY have arrived
(`relay.RelayUnclear`) is never sent again and never silent: it is recorded as a turn start
all the same, so a house that did not take it and sits idle with no Stop is the quiet rule's
([the drain](30-drain.md)), and the card and the answer say "may not have arrived ... tap
Resume". Two live sessions named for the card (a stale twin) are refused by the harness, so
the card says so with both session ids and nothing is told, resumed or stopped: the stale one
is the user's to stop. Only the decision holds the card's lock; the relay (7 to 17 s) runs outside
it, and for the user's taps on the deck and the drain's carries on a thread of its own with its own
board, at most four at once (`tellhouse.TELLS_AT_ONCE`), so the tap answers "the message is
on its way" at once and one slow tell does not hold up another card's. A card keeps its
newest ten `told/` files (`tellhouse.TOLD_KEEP`); the board keeps every prompt in its
`resume` event. A tell passes no flags, so a model changed since the house started applies
at its next real resume.

**The user's tap for a WORKING house is held, never dropped to a note** (c-598). The probe found a
message into a busy session queued and folded into the running turn at its next tool
boundary, which is safe but lands inside work in progress, so Keel waits for the turn to end
instead. The hold is the board's: a `resume` relay nobody has carried
([the drain](30-drain.md), "Relays"), addressed to the house's machine, which on the deck's
own machine is `actions.hold_here` writing one for this very host. The house's Stop hook
(`bin/keel-turn-end`) kicks that machine's drain when such a relay is pending
(`kick.after_stop`, `keel/kick.py`), and the drain tells the house.

**And while the user is in it at a terminal** (`house.refuse_if_in_terminal`, U3): a row the
listing gives as `kind: interactive` for the card's session, or a drop-in hold that still
holds, raises `house.InTerminal`, a `Busy`, so every caller above treats it the same way.
The deck's Resume house tap checks it before it relays too, so the refusal comes at the desk, not later at the relay.

Retry is different: it unblocks, stages `assigned` and runs one explicit drain pass, so a
fresh house starts on the same card.

**A resume is REFUSED while voice is talking to the house** (`options.voice_hold` on the
card, [the talker and voice](50-talker-and-voice.md)). A conversation takes its turns into
that same transcript, so a resume mid-sentence is the race the hold exists to stop, and
that covers the deck's Resume house button, a relayed tap and the drain alike, because all three
come through `house.resume`. The user's own answer at a gate is the exception: Approve and Send
back pass `force`, which releases the hold instead of being refused by it.

**A shipping house lives on and answers review in its own session** (lane SHIP, c-600,
`keel/shipping.py`). The user's Approve outcome moves a work card to `shipping` and ends nothing:
the build house stays, idle, holding no pool slot. When its pull request draws review the
drain TELLS that same house the batch (an idle house by a message, an exited one by one
resume; "The user's taps, told in place" above): the items, the adapter's method for judging
them, and Keel's protocol. The house judges every item, commits only what is valid, drafts
a reply otherwise, runs `keel check` after a commit, records one `kb verdict` per item, and
ends its turn; the card never leaves shipping. It is fenced from publishing by mechanism:
the house guard (`bin/keel-house-guard <card>`, a PreToolUse hook on Bash) reads the card's
stage LIVE for a command shaped like a push (`git ... push`, the adapter's `pr` or
`publish`) and refuses it at shipping, because the session's permissions were fixed when it
started at building, where it had to push; a board it cannot read holds the push (the one
place it fails closed); and any resume rewrites the settings with the adapter's `deny`,
which at shipping denies the same. See [the drain](30-drain.md), "Shipping".

On ANY stage the same guard also refuses a push to a SHARED branch of the card's space flow
(c-641): every flow branch whose kind is not `card` or `work`, so a work card's base,
`dev_review` and `master`. `keel/flowfence.py` reads the command's destinations in the
session's cwd (an explicit `HEAD` is the branch of the same name; a bare `git push` counts its
upstream too; `--all` counts as every branch), and the flow from the config the hook's env
names, all read in one `kb flowinfo`, judged on the board, and only for a command
that pushes. A push it cannot read, or one aimed elsewhere by an alias, a push config, a
variable or `xargs`, counts as every branch (the list is in [flows](64-flows.md), "The push
fence", with the guard's boundary: it reads command lines, it is not a sandbox). The only way
through is `kb flowpush`, under the user's grant ([flows](64-flows.md)). A board it cannot read holds
the push, as before.

**`keel check <card>`** (`keel/fixcheck.py`, c-600) is the one command a house runs after
it commits at shipping: it scales the review of the new commits and says the next step.
The review stamp already covers HEAD of every worktree: nothing to run. A closed review pass
whose stamp has a reviewed head for every worktree, and at most 150 changed lines since
(`FIX_MAX`): a FIX CHECK, `prep --since` from the stamp and ONLY the verifier on that delta.
Anything else: a FULL PASS, a full `prep` and the reviewer, then the verifier. The stamp
the SubagentStop hook writes is the ONE receipt (the hook keeps its own rules, so a fix
check that earns a full review still says so); the drain reads it for Ship's "unchecked"
warning (`shipping.local_facts`).

**Rotating a house** (`keel/rotate.py`, R6 of the overnight clearance, decision N9) is the user's
flow, on demand only. It shipped DORMANT and is ON in the shipped example, and on the owner's install since 2026-09-24; `[keel] rotate = false` hides the Rotate session
button, refuses `house.rotate` and `keel rotate`, and no drain carries a `rotate` relay. With
it on: the deck's Rotate session (`house.rotate`, relayed as a `rotate`) or
`keel rotate <card>`. Two phases,
because the checkpoint is a model turn and a tap may not wait on one:

1. **Ask.** Refused while voice holds the card, while the house is working (the checkpoint
   turn is a resume, `house.Busy`), and while a rotation is already under way. The house is
   resumed with a prompt to commit, write a handoff checkpoint to
   `state/cards/<id>/handoff.md` (the `handoff` skill's checkpoint mode where the machine
   has it, the same sections by hand where it does not) and bring `context.md` up to date,
   then end its turn. `options.rotate` records `checkpointing`, and `kb stop-check` lets that
   turn end at `building` rather than nudging it back to work.
2. **Finish**, on the drain's next passes there (`drain.rotate_upkeep`). Once that session
   is no longer working and the checkpoint was written after the ask, a FRESH session is
   started with the card's own brief plus a rehydrate section (read the checkpoint, then
   `context.md`, carry on from "What is left"), recorded with `set_session`, so the deck,
   voice, the relays and every other reader follow it; the checkpointing session is stopped
   as superseded, and the card says so. A turn that ended with no checkpoint (after a two
   minute grace), or one still working after thirty minutes, drops the rotation with a note
   and leaves the house as it was.

   **It acts only on the session it asked** (lane E review finding 2): any resume after the
   ask (a Send back, the drain's own) clears `options.rotate` in `house.resume`, and a pass
   that finds the card on another session than `options.rotate.session` drops it. A fresh
   session that will not start is tried once more on the next pass, then the rotation ends
   with a note; it never loops, and the card is never left exempt from the Stop nudge.

   **One per-card lock** (`house.card_lock`, `state/locks/card-<id>.lock`) is taken by
   `house.resume` and by the finishing pass around the fresh start and its record, so a
   resume and a rotation cannot interleave (round 3, finding 2). The new session is recorded
   FIRST, by compare-and-swap (`kb session --expect`: only while the card is still on the
   rotation's session); if the card moved on, the session just started is stopped rather
   than left running unrecorded. What comes after the record (the csr sidecar, the reviewer
   mark) is a note when it fails.

Nothing rotates by itself. On the automatic half, what Claude Code 2.1.280 reports is
recorded in `<install>/history/docs/decisions.md` (E-8): no context figure in `claude agents --json` or in
any hook payload; the status line's JSON carries `context_window.used_percentage`, and the
`PreCompact` hook fires with `trigger: auto` when the harness itself decides the context is
full. Neither is wired to anything.

`house.wake` is the other half and it is NOT a resume: `claude --resume <id> --bg` with no
flags and no prompt puts a stopped session back with the options it was started with,
keeping the same uuid and the same `claude.ai/code` link, so it costs no model turn and the
card needs no new session recorded. It is what ends a voice conversation, and what
`drain.release_holds` runs on a hold that ran out. A build of `claude` that does not keep a
session's saved options answers with a copy under a new id instead; that is a resume in all
but name, so it is recorded like one.

The user's deck's **Resume and open in app** (V2-2, `keel/openapp.py`) is the third caller: the wake
under the card's lock after `refuse_if_busy`, so a working house, a session open in the user's
terminal and a Drop in hold refuse it exactly as they refuse a resume, then the link of the
session the card is on now ([the deck](40-deck.md)).

## Where it lives

- `keel/house.py`: the settings file, the brief, the worktree, launch and resume.
- `keel/prompts.py`: every sentence Keel says to a house that is not the contract.
- `keel/ending.py` and `bin/keel-turn-end`: the turn-end half of the Stop hook.
- `keel/briefnews.py`: the brief's card block, and the news a live house has not heard.
- `keel/review/` (`agents.py`, `findings.py`, `standards.py`, `risk.py`, `repo.py`,
  `brief.py`, `prep.py`, `stamp.py`, `gate.py`, `stagecheck.py`): the review core and the
  pre-gate pipeline; `bin/keel-review` and `bin/keel-review-stamp` run it.
- `keel/dropin.py`: the command Drop in hands out.
- `bin/keel-board-fence`: the PreToolUse(Bash) hook a confined house runs under.
- `bin/keel-house-guard`: the PreToolUse(Bash) hook every house with a shell runs under: the
  `pgrep -f` loop, a push at shipping, a push to a shared branch of the flow (c-641), and
  the space pack's own `guard` verb when it ships one (c-689).
- `keel/housejobs.py`: a house's background jobs, read from the harness's job record, and
  the stop that ends them by pid; and the one rule for a working house (`working`).
- `keel/housemem.py`: the memory a live house holds, its process tree's RSS (c-607).
- `keel/idleclose.py`: Close idle house, the rule it is checked against and its note (c-607).
- `keel/afresh.py`: the fresh start of a house whose conversation the harness no longer
  holds, the three conditions it needs, and the block for the user when they do not hold (c-654).
- `keel/shipidle.py`: the drain's three ends of an idle house, a merged card's and a shipping
  house idle over two hours (a-72), or whose turn on a re-offered batch ended (c-651), with
  what that turn left unjudged handed to the user (c-654).
- `keel/livetail.py`: what a house is doing now, from its job record and its transcript's
  tail, for the deck's live strip ([the deck](40-deck.md), "The live strip").
- `keel/ghosts.py`: the doctor's `ghost houses` line, rows listed as working with no process.
- `keel/harness.py`: the only module that runs the `claude` binary.
- `keel/trust.py`: the house's cwd trusted in the space's `.claude.json`, and forgotten after.
- `etc/house-contract.md`, `etc/house-contract-drop.md` (the house with no shell),
  `etc/space-work.md`, `etc/space-personal.md`.
- `etc/house-bin/open`: the `open` a house finds first, which opens nothing.
- `app/theme-work.css`, `app/theme-personal.css`: the palette a surface links.
- `state/cards/<id>/`: settings, brief, plan, context, assets.

## How to change it

- A new rule for houses: make it a mechanism first (a deny, a hook, a missing command). If
  it can only be prose, it goes in the contract, which stays under 60 lines, and it comes
  out again the moment a mechanism can carry it.
- A new prompt: `keel/prompts.py`, with a test in `tests/test_prompts.py`. The deck's
  taps, the drain's resume and the house's own loop all have to agree on what it was told.
- The harness facts that cost real time are recorded in `tests/fixtures/harness/README.md`
  and the live runs in `<install>/history/tests/live_house.md`. Read those before assuming what `claude`
  does.
