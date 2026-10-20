# Bosun

Bosun is Keel's builder: ONE Claude Code session, running on this machine as the user Keel
runs as, that the user reaches from the Claude app, with its own page (`/console`) and its own memory
(the install's `memory/bosun/`, "Its memory" below). In builder mode it builds the personal cards that have a repo and lands
them on `next`; the user's deploy puts them live. The design is c-517's plan; this page is how the
parts BO-1 (c-519), BO-2 (c-520), BO-3 (c-521) and BO-4b (c-526, its outcome approvals onto
the integration branch `next`, and the user's deploy ask) built actually work. BO-5 (c-523) gave
Harbor its tools for Bosun ("Harbor and Bosun", below), and BO-6 (c-524) its compaction and
the Journal's throughput and gaps. c-591 reshaped its page into Now, Queue, Shipped and
Journal over the cards it builds ("The page and the entry", below). c-593 retired what came
before builder mode: the console space (its own board), driving a card, the user's grants and the
three strikes ("Retired in c-593", below).

This Bosun is not the older one in `<install>/memory/talker/bosun-and-the-atlas.md`, which the Keel
rebuild retired on purpose; that page is marked as history, and Harbor's memory of this one
is `<install>/memory/talker/bosun.md`.

## The session

`keel/console.py` owns it, and `keel/consoletaps.py` holds the taps on it: every call there is the user's tap.

| Verb | What it does |
|---|---|
| `keel console start` | resumes the last session when `state/console.json` names one, else starts a fresh one |
| `keel console restart` | stops it when it is up, then starts a FRESH session from its memory |
| `keel console stop` | stops it; its conversation stays, and Start picks it up again |
| `keel console status` | the strip's facts: up or not, idle or working, the app link, the last turn, the context used |
| `keel console memory` | prints its memory (`console.memory_dir`), index first: what its SessionStart hook runs |

What a tap types into the session names no one but "the user" (c-731): a fresh start is
"You are Bosun, started fresh by the user's tap. Your memory is in your context above. Say
in one line that you are up, then wait for the user." (`console.START_PROMPT`), and a
resume is "Started again by the user's tap, after a Stop. Carry on from where you were; if
nothing was in hand, say in one line that you are back and wait." (`console.RESUME_PROMPT`).
The hello check and the handoff note leave both out by matching them word for word
(`consolehandoff.KEEL_PROMPTS`, [onboarding](89-onboarding.md)).

Each runs where the config has a Bosun (`console.configured`): an install, or a config whose
`[console]` table names a `host`. Any host named is this machine (c-622), so the key only
says there is a Bosun; the shipped example (`etc/shipyard.example.toml`) names none, and every verb is refused there
(`console.refuse_unconfigured`).
Start and Restart are `claude --bg --name Bosun --remote-control Bosun` in Keel's root, with:

- **the user's interactive permission mode** (`[console] permission_mode`, `auto`), not a house's
  fence: no `--restricted`, no worktree, no `KEEL_CARD`.
- **its config dir** (the personal space's, `console.SPACE`, `console.config_dir`:
  Bosun takes that space's deny list and model, since every card it builds is personal), so
  no work credentials. It does not take the space's `allow` list, which is for that space's
  houses ([houses](20-houses.md)): the allow rules of its session are its own
  (`console.kb_allow`, `console.builder_allow`, `builder.build_allow`).
- **settings at `~/.config/keel/credentials/bosun-settings.json`** (0600, beside the shared
  key; `housetier.bosun_settings_path`, c-553), written on every start: the SessionStart
  hook, the UserPromptSubmit hook that puts the open requests atop the user's message ("Requests",
  below), the stack guard every house gets (`house.guard_hooks`: `[machine] stack_guard_hook`, a
  script outside every space's config dir, so personal's does not carry it), the space's deny list plus `house.secret_deny`
  (the user's token file and the house key), the shared house key and the work space's config
  dir (`console.reach_deny`: the work credentials live there and Bosun holds none), plus
  its own lifecycle (`keel console start`, `stop`
  and `restart` are denied to its Bash, and `keel console` refuses them under
  `KEEL_BOSUN`), and its key as `KEEL_BOSUN` in the settings' `env`. Bosun's tools and every
  house are denied the file itself (`console.reach_deny`, `house.secret_deny`), and its guard
  refuses a write that names it however its directory is spelled (`console.guard_verdict`). The denies are rules for Claude's
  own tools, a speed bump rather than a boundary: a shell that spells a path another way
  gets past them, as for a house.
- **an environment built for it** (`console.launch_env`): the config dir, `KEEL_HOME`, and
  for an install's builder `KEEL_CONFIG`; never the key (c-553), which a launch
  that started the config dir's daemon would hand to every spare, and so every house, after it. The user's token is withheld
  as from every child (`keel/childenv.py`), and there is no `KEEL_CARD`: `harness.start_bg`
  takes the environment whole rather than building a house's.

Resume mints a new session id and a new app link (probed 2026-09-17), so a Start after a
Stop records both again; the new session carries the whole conversation (proved
for c-519). Restart asks for a confirm on the page, because it ends the conversation. A
Start whose session can no longer be resumed says so and names Restart as the way out.

A tap reads the listing strictly: when `claude agents` itself fails, Start, Stop and
Restart refuse ("could not tell whether Bosun is running") rather than take a failed listing
for "not running" and launch a second Bosun. A Restart writes its stop before it launches,
so the Journal keeps it when the launch fails. When a launch did not see the app link in its
few seconds, the next status asks the log again and keeps the link.

**A stuck Bosun** (c-530): a background session whose process died stays in `claude agents
--json` with no `pid` and no `status` (probed by killing one; a stuck copy looked
the same, state `blocked`). `console.stuck` names such a row by the listing's own shape,
never by probing a pid, since whether a session is alive is the harness's to say. A
live session waiting on its user is `blocked` too, but it has both, so it is not stuck.
Status says `stuck` and not up, so the page offers Start. Start and Restart try `claude stop`
on it and write the Journal either way. When the stop
was confirmed, Start resumes the conversation as usual; when it was not, Start starts a
FRESH Bosun rather than resume a session the harness still lists (that would be a copy).
Restart is always fresh. Stop records it rather than refusing. Before this, all three read the row as up and refused.
Every one of those stops is `housejobs.stop` (c-534): `claude stop`, then the background
shells the session left, ended by pid ([houses](20-houses.md)).

One tap at a time: each takes an exclusive lock on `state/console/lock`, and a second tap
while one is being carried out (the desk and the phone at once) is refused rather than
launching a second Bosun the file would forget.

### What `state/console.json` holds, and what it does not

The session it last started (`session_id`, `bg_id`), its app link, when it came up, and the
last twenty taps on it (what, by whom, when, which session). Whether Bosun is UP is never
kept there: `console.status` reads `claude agents --json` every time, and says `idle` or
`working` from the row's own status, `stuck` when the row is listed with no process (below),
`stopped` when the row is gone, `never` when no session was ever started. The last turn, the model and the context used come from the transcript's
last 256 KB (`console.turn_facts`): the newest record's time, and the newest main-thread
assistant usage (input, cache read, cache creation and output tokens) against
`[console] context_window`, since no log states the model's window. `compact_at` is where
the page draws the compaction mark, and where the harness compacts ("Compaction", below).

Nothing starts, stops or restarts it by itself. The user's answers to its asks and a house auto
mode paused reach it as a message into its live session ("Asks" and "A paused house",
below), never by a stop or a start. The drain matches sessions to cards by name
(`drain.house_ids`), so a background session named `Bosun` in personal's config dir is never
counted, reconciled or stopped by it.

## Compaction and the handoff note

Bosun compacts at `[console] compact_at` (70) percent of `[console] context_window` (1M), in
the same session, so its id and its app link never move (c-524, `keel/consolehandoff.py`).
Nothing in Keel watches the meter: `console.compact_env` puts
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` and `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` in its settings'
`env`, and the harness does the rest. The same `env` empties `KEEL_CARD`, which the daemon's
process can carry from another card's house, so Bosun's `kb` and hooks are never a house.
Bosun's key rides in the same `env` for the same reason (c-536, c-553): below. The binary takes the threshold as the window times the
percent, at most the window less 13k, and clamps the window to 100k..1M.

They go in the SETTINGS, not the launch's environment: a `claude --bg` session is claimed by
a spare process the daemon started earlier, and neither it nor its hooks see the environment
of the command that launched it (probed 2026-09-26 on 2.1.283: the hooks of a
session launched with the two variables saw only the daemon's `KEEL_CARD` of another card;
with them in the settings' `env` it compacted at the threshold). The probe's files are in
`state/cards/c-524/assets/probe-bg/`. Compaction came at the start of the session's next
turn, not in the middle of one.

**The handoff note.** Before it summarises, the harness runs the PreCompact hook, `keel
console handoff` (`consolehandoff.main_hook`, timeout `console.HANDOFF_TIMEOUT`, 20s). No
hook can make Bosun take a turn first, so the note is built from the record:

- when, the trigger (`auto` or `manual`), the session, the context used before it;
- `kb console list` and `kb console asks` as the board prints them, five seconds each
  or the line saying why one is missing;
- the user's last three messages and Bosun's last reply from the transcript's tail (a hook's
  output, the harness's own reminders and command echoes, Keel's start and resume prompts,
  the drain's relayed messages (recorded as meta), tool results and subagents are not the user's).

Keel's prompts are left out by matching today's wording word for word, and the wording
changed in c-731. A session started or resumed under an earlier wording keeps that prompt
in its transcript, so until three real user messages follow it (or it leaves the last 256
KB the note reads), a handoff note can list it as the user's message. A Restart of Bosun
clears it for the handoff; the hello half is in [onboarding](89-onboarding.md), "The hello
check".

It is written to `state/console/handoff.md`, the one before becoming `handoff-<its
time>.md`, five kept. Then (never before the note is on disk) a `compacted (auto) at 71%, handoff written` row, by `harness`, goes in
`console.json`'s history under the tap lock (waited for up to five seconds, so the two
reads and the wait stay inside the 20; a row it could not write is a line in what the hook
prints, below the note, and the note is still handed over). What the hook prints, the note under a line telling the
summary to keep what the user last asked and every id, is appended to the compaction's
instructions. It never blocks a compaction (exit 2 would): any failure is one line and
exit 0.

**After it.** The SessionStart hook fires again with source `compact`, and `keel console
memory` (`consolehandoff.session_start`) prints the memory and then the note, so Bosun
resumes from the record: only a note of this session written in the last ten minutes
(`FRESH_SECONDS`). Otherwise (the hook failed, or never ran) it says no note was written and
sends Bosun to the board, since an older note handed over as current would be worse than
none. A start or a resume is the memory alone. Probed on the harness:
the summary kept the words the PreCompact hook gave it, and the model read what SessionStart
printed after the compaction.

`keel/consolehandoff.py` is one of Bosun's authority paths: it decides what Bosun keeps.

## Who Bosun is to `kb`

`KEEL_BOSUN` in its environment makes its `kb` actor `bosun` (`cli.resolve_actor`), and it
wins the way `KEEL_CARD` does for a house: over the user's token, and over `--actor` (asking for
another actor is refused). `--actor bosun` from anyone else is refused too, and so is the
flag beside a `KEEL_CARD`: a house is never Bosun.

**The flag holds Bosun's key** (c-522), and a flag without it is refused, never taken for
Bosun. The key is derived from the shared key (`housetier.shared_path`,
`~/.config/keel/credentials/house-key`, which `shipyard init` mints):
`authority.key_of`, an HMAC of it. `console.settings` puts it in the `env` of Bosun's
settings file, and nowhere else (`childenv.WITHHELD` keeps it from anything a `kb` holding
it starts, a house it resumes above all), and `console.key_of` refuses to start Bosun on a
machine with no shared key. **Why the settings and not the launch environment** (c-536, the user's
answer on c-553): a `claude --bg` session runs in a spare the config dir's daemon spawned
earlier, whose environment is the daemon's, fixed by whichever `--bg` launch started it (every
spare can carry one card's `KEEL_CARD`). So a key in the launch
environment reaches Bosun only when Bosun's own launch started the daemon, and then reaches
every house that daemon runs after it. The `--settings` file reaches every session, `-p` turn
and hook, and a flagless `--resume --bg` wake keeps it. The file is 0600 in the 0700
credentials directory beside the shared key, outside `state/` so no backup carries it; whoever
can read it could already read the shared key the Bosun key is derived from. Every house's
settings `env` sets `KEEL_BOSUN` to empty (`house.env_for`), which `cli.resolve_actor` reads
as unset, so a key an older daemon still carries never rides into a house. Bosun's tools are denied the shared key
(`console.reach_deny`) and so is every house (`house.secret_deny`). Bosun's `kb` checks
its key against the one it derives itself. A new shared key means a Restart of Bosun. It is
not the user's token on purpose: `human` is the deck's own token, which Bosun never holds.

## Its memory

The install's `memory/bosun/` (c-722, "Where the memory lives" below): `MEMORY.md` (the index), `identity.md`, `needs-you.md` (what always goes to
the user), `authority.md` (what bounds it: the board's refusals, two hooks and the deny rules on
its tools, said as rules it keeps and not as walls),
`builder.md` (how it builds, lands and tracks Keel's work, and what it does about a paused
house), `requests.md` (how a request reaches it and how it takes and ends one), `asks.md`
(how it asks the user anything), `runbook.md` (where things run, a deploy, the drain, its own
session). The SessionStart hook prints them on start,
on resume and after every compaction, so its identity is mechanism rather than a prompt it
may lose. Each file is headed by its full path, so Bosun knows where its memory is.
`console.MEMORY_FILES` is the list and its order; `tests/test_console.py` holds the shipped
template to it. In builder mode Bosun changes them on a personal card, and says in the card
what the change does to it.

### Where the memory lives (c-722)

`keel/memoryroot.py` is the one answer to "where is this memory", for three parts:

| Part | In the install | Read by |
|---|---|---|
| Bosun's memory | `<install>/memory/bosun/` | `console.memory_dir` (the SessionStart print), the first run's How Shipyard remembers panel |
| the talker's memory | `<install>/memory/talker/` | `talker.Paths.memory_src` (the auto-memory link), `refresh.memory_stamp` (its rotation) |
| the talker's rulebook | `<install>/memory/talker/CLAUDE.md` (`memoryroot.RULEBOOK`, c-722 landing B) | `talker.Paths.rules_src` (the config dir's `CLAUDE.md` link), `refresh.memory_stamp` |
| the user's profile | `<install>/identity/` | both, by path, from their memory |

`<install>/memory` is a git repo on `main`, as the install's packs are, so a change to it is
a commit that can be read back. The talker writes its own memory as it talks; those writes
stay uncommitted, and only a commit moves the stamp it rotates on.

**Changed on a card, as packs is (r1.F1).** The memory repo is one of the install's own
repos (`builder.OWN_REPOS`): `shipyard init` (once it is a repo) and `shipyard move-personal`
list it as the personal repo `memory` and add it to `[builder] repos`, and the builder works
on it in its own clone, `<install>/builder/memory`, never the live repo, which the guard holds
("Its own authority" below). The user's Approve outcome lands it as it lands packs: no
integration branch, a fast-forward of the live repo's `main`. The talker's uncommitted writes
do not stop a landing unless the card changed the same file, and then git refuses the merge
and the card says so. Setup, readiness and the deck do not count it as one of the user's
repos.

**Seeded once, never overwritten.** `shipyard init` copies `templates/memory/<part>` and
`templates/identity` into each part the install does not have yet (`memoryroot.seed`), commits
only the files it seeded (a re-run sweeps nothing the talker or the user wrote), and records each template file's hash in `memory/.seeded.json`. A part that
exists is never written again. When a shipped template moves on, `keel doctor` says which
file changed or is new (`memoryroot.template_news`, a `memory` line, never a problem), and
the user's copy stays theirs to compare.

**The checkout, only while the install has none.** Before c-722 the memory lived in the
code checkout (`bosun/memory`, `<checkout>/talker/memory`, `<checkout>/identity/`). `memoryroot.dir_of` answers
the install's directory once it holds the part (its `MEMORY.md`, or for the identity any
profile) and the checkout's until then, so an install from before keeps working until
`shipyard move-personal` (88-install.md, "Moving your own things into the install") brings
its memory in. Init does not seed a part the checkout still holds, since the templates would
hide the user's own memory; it says so on its `Memory:` line, and the doctor names the parts
still read from the checkout.

### The templates a new install starts from (c-699)

`templates/` holds what a NEW install's agents start with, written for any user and no one
user:

- `templates/memory/bosun/`: the builder's memory, the eight files named above, for the
  one builder an install has (so there is no separate in-app file). Since c-734 its
  `builder.md` says to build each card through a builder sub-agent in its own isolated
  worktree with a self-contained brief, Bosun keeping the plan, the review order, the
  answers and the landing, so it stays free to talk with the user (the second stranger run's
  Bosun built a connection of about 3000 lines in its own session and could not draft the
  user's flow meanwhile); and its `asks.md` says an option that moves something says so.
- `templates/memory/talker/`: the talker's index and six entries (the engine it sits on,
  cards from conversation, what needs the user, a spoken turn, drawing, the deck).
- `templates/identity/about-you.md`: the profile a user fills in, every line a prompt.

`shipyard init` seeds a new install from them, once and never over what is there ("Where
the memory lives", above).

**The rule for writing one: the lesson, never the story.** A template keeps the rule, one
sentence of why, and how to apply it. It names no person, no machine, no card and no date.
A lesson that a mechanism now holds is not repeated as prose: the template points at the
Atlas page, by path and section title. A lesson that is one user's taste, or one machine's
limit, is left out or offered as a default the user can change, and said to be one: how
many cards a plan becomes, how many builders and test runs at once, reproducing a bug
before its fix, the test written first, the design weighed first, how short an answer is,
whether a carded thing waits in the inbox, and the order of the builder's queue. What a
template says the engine allows or refuses is said per builder mode, as the authority rules
decide it ("What Bosun may do"): the Guide builder approves no gate, the Full builder may
approve the plan and the landing outcome of a card it builds, and neither approves an
outcome that goes live, a work card's gate or the deploy. A template says of tests only what the
engine does for any repo: run what the change reaches before review, and the landing runs
the suite on the merged tree.

`tests/test_templates.py` holds every template to it: each is there and no other, under 80
lines, with no "he", no machine word, no pack's own word, no id, date, port or home path.
Every Atlas pointer lands on a page, and a title it quotes must be one of that page's
headings or a bold lead-in opening a paragraph, a list item or a table row (a heading's
closing tag such as a card id is left out, since a template names no card); a phrase in
running prose does not count. Every other file a template names in backticks resolves
too: a bare page name (`96-bosun.md`) to the Atlas, a sibling (`asks.md`) to the same
folder, the identity file by its folder and name to the templates. That check cannot tell whether a
default is worded as one: that part is read by a reviewer. Every deck control a template
names (`CONTROLS`, and any "Open in ... app") must be a label the deck draws, word for word.
The owner-words guard reads
them too ([Extending Shipyard](63-extending.md)).

For any new pack, segment or deck view, the page Bosun follows is [Extending
Shipyard](63-extending.md): `keel new pack|segment|view <name>` gives the checked starting
point, inside the card it is already building (it files no card of its own), and that page
gives the rules each kind is held to. A connection to a code host starts on the pack kit
(`keel new pack <name> --kit`, c-735): the draft choice's brief has Bosun write only the host layer,
its stand-in and its sentences, never a copy of another pack, and finish when `keel pack
check` is green ([onboarding](89-onboarding.md), "Where finished work goes"). The second
stranger run's connection, before the kit, was 6252 lines, about 72% of them a port of the
GitHub pack; the Gitea pack on the kit, its tests included, is under a third of that.

## The setup conversation (c-678)

On a new install the first run hands Bosun the part of setup that depends on the user's
code ([onboarding](89-onboarding.md), "Set up your repos with Bosun"): Bosun reads each
repo, asks what the code does not say, and drafts its CLAUDE.md, in its own session. The
page never draws Bosun; it shows what comes back.

What makes that a mechanism and not a promise:

- **The draft card.** Only the user may make a proposal card (`board.PROPOSAL_OPTIONS`), so
  the user's own Add files it: copying a repo in leaves a card `Draft the <space>/<key>
  CLAUDE.md` in personal (`tiercards.open_draft`, `onboarding.leave_draft`), carrying
  `tier_proposal` and `tier_draft`, at `inbox`, where nothing starts a session on it. Its
  brief names the repo's folder, the file to write and the lines Keel reads. It is a
  personal card with no worker named, so in builder mode it is Bosun's to stage and note
  (`authority.builds`).
- **A flow is drafted the same way.** How work ships files `Draft the <space> flow` by the
  user's tap (`flowcards.open_draft`, with `flow_proposal` and `flow_draft`), Bosun writes
  `flow.toml` in its folder for the card and stages it, and the page puts the draft beside
  the flow the space has now ([flows](64-flows.md), "A draft Bosun writes with the user").
- **The stages are the page's states.** `inbox` is "not started", `kb stage <id> building`
  is "Bosun is drafting", `kb stage <id> review --output <file>` is "ready for you".
- **Where the draft is.** Bosun writes it in its own folder for the card,
  `<install>/builder/cards/<id>/claude-md.md`, never in the user's tier. Adopt reads the
  card's own directory first, then that folder (`tiercards.draft_path`): two fixed places,
  nothing a card names.
- **Read only.** The guard above refuses an edit inside any repo the install copied.
- **Adopt is the user's.** `onboarding.adopt_proposal` writes the file by the user's tap, as
  for every proposal; Bosun's approve of a proposal is refused by the board.
- **A line runs only from text the user adopted or saved** (c-678 review,
  `keel/tierrecord.py`). Keel runs the prepare and test lines of a repo's CLAUDE.md, and
  takes its run rule and landing branch from it, only while the file is the text the user
  last adopted or saved ([onboarding](89-onboarding.md), "What Keel does with an adopted
  file"). A file changed any other way, Bosun's own write included, runs none of its
  lines, and the card says so. Where the repo's test command would have come from that file
  (the config's `[tests]` names none) and Keel lands the work itself (a space with no
  pack), the landing of its repo's cards is refused until the file is adopted or saved
  again. So a change to a line goes through a draft and the user's Adopt, or the
  user's own Save on the Setup page; it is never Bosun's edit of the file.

How Bosun is told to run the conversation (the order of the steps, what to ask, the file's
shape from `etc/claude-md/`, drafts only) is its memory's business. That text is proposed
for a new page of its memory, `setup.md`, and is not in this checkout yet: `bosun/memory` is an authority
path, and c-678's builder left the text for the owner to take (`console.MEMORY_FILES` would
then list it).

## Retired in c-593

Until c-593 Bosun had its own board, the `console` space (`[spaces.console]`, its contract,
its `aside` key that kept it off the switch, and its in-flight cap of three, `in_flight_max`,
held by the drain), and it could drive a personal card the user marked (`options.driver`), pass its
gates under the user's grant (`options.grant`, `kb grant`), and move its house at most three times an
hour (the strikes). Builder mode replaced all of it: Keel's work is a personal card with its
repo, which Bosun builds itself. So c-593 removed:

- the console space and its keys (`aside`, `in_flight_max` and its old name `open_max`), its
  contract, its cap, and the deck's `console` scope (now `bosun`, "The page and the entry");
- driving: `kb console read`, `rotate` and `note`, the non-repair `resume` and `retry`,
  `derived.driving`, the driven brief a house got, and the driven-card wakes (a staged plan or
  outcome, a block, a failed resume, the review limit);
- `kb grant`, the grant check, the plan-gate approval by Bosun, and the outcome checks that
  only driven and console cards met (Risk, open findings, the fence); builder mode had
  already skipped them;
- the strikes and the intervention count (`authority.refuse_intervention`).

**Old records stay.** The console cards on the board are done and archived, and still load:
`kb show`, `kb list --all` and the deck with Include archived read them like any card, and
the deck's `needs_you` and Harbor's digest leave out a card of a space no longer configured.
A new one is refused to everyone (`authority.refuse_create`; `kb create` already refuses a
space the install's `config.toml` does not name). An old card's `options.driver` and `options.grant` are
inert: nothing reads them, and the deck does not list them. `intervene`, `wake` and `grant`
events stay readable.

`app/theme-console.css` and `html[data-mode="console"]` in `app/ui.css` stay: they are the
Bosun page's palette, graphite with the iris accent #A59BFF, held to each other and to 4.5:1
by `tests/test_theme.py` like the other two. `console.LABEL` is the same name where a card's
space would go for Bosun on the voice page.

## Reaching it

The board, the deck and Bosun are on one machine. The deck reads Bosun's status itself
(`console.view`), at most every ten seconds; a tap drops the held one (`console.forget_view`).
A config with no Bosun has no `console` entry in the state, and the page says `away` for it.
The taps `console.start`, `console.stop` and `console.restart` are deck verbs
(`actions.act_console`, which runs `consoletaps.tap`), refused with one line on a config with
no Bosun (`console.NO_BOSUN`). They are page
verbs: every action is the user's, proven by the page (`keel/deckauth.py`), and a body with a
`caller` is refused (`actions.refuse_caller`). Never a relay: a tap is carried out or refused
at once, not kept for later. Until c-622 Bosun could run on another machine than the deck,
which drew the status that machine's drain pushed and reached its taps through a door; c-648
removed what was left of that (the pushed and tapped status, the `away` of a far machine, the
host comparison).

## Requests

A request is Keel getting in its own way, filed with Bosun (c-520, `keel/requests.py`). It is
a row in the board's third table, `requests`, numbered `r-N`, and every move on it is a
`request` event under that id, which is what the Journal reads. It is not a card: it shows
in the Bosun page's Intake, never among its cards.

| Verb | Who | What it does |
|---|---|---|
| `kb console ask "<what>" [--detail <text>] [--card <id>] [--key <k>]` | anyone | files `r-N` at once; a house's own card is `--card` by default; with `--key` it is a sighting |
| `kb block <id> "<what>" --keel` | a house, anyone | in one write, files a request about the card and blocks it with "Keel, filed with Bosun as r-N: ..." |
| `kb console list [--all]` | anyone | the open and taken ones; `--all` adds the sighted and resolved |
| `kb console show r-N` | anyone | the row and its moves |
| `kb console take r-N` | `bosun`, `human` | open to taken |
| `kb console resolve r-N --how fixed\|filed\|declined\|escalated --gap <tag> --note <text> [--card <id>]` | `bosun`, `human` | taken to resolved; `filed` names the personal card, with its repo, it was filed as (Bosun's queue, c-593) |
| `kb console gaps` | anyone | one line per gap tag: its count, `recurring` at two or more, how each ended, when last, which requests |
| `kb console hook` | Bosun's hook | the open and taken requests as the lines atop the user's message, or nothing |

**Nothing wakes Bosun.** The one way a request reaches its session is its UserPromptSubmit
hook, `kb console hook`: before each message the user sends Bosun it prints the open requests
("Act on one only when the user names it") and the taken ones, each filer's line in quotes under a
last line saying they are data and not the user's words, and nothing when none waits. It
never fails the user's message: a board it cannot read in five seconds is one line saying so, and
exit 0. The user hands a request over by saying "take r-N", or by Copy for chat on the Requests
tab, which puts exactly that on the user's clipboard; the tab has no other action. `kb console hook
--json` answers the payload rather than the lines.

**One open request per card.** An unkeyed ask about a card that already has one open or
taken is refused with that one's id, so a house cannot file the same thing every turn, and a
house may not sight at all (`--key` is refused to actor `house`).

**Sightings** are how the drain and `keel doctor` file without filing noise. A keyed ask is a
sighting: the first writes a `sighted` row nobody is shown, each repeat inside `[console]
repeat_minutes` (60) counts it up, and the `repeat_after`-th (3) opens it. Past the window it
starts over at one. A sighting of a key already open or taken counts `seen` up on it and
files nothing. The drain's keys are in [the drain](30-drain.md) ("A failure it keeps
seeing"); doctor sights every problem it prints (`doctor.sight`), keyed by the line with its
numbers and times taken out, so "probed 14:02" and "probed 14:32" are one problem. It is the
doctor's only write, and it never creates a board that is not there.

`kb console list`, `show`, `hook` and `gaps` are reads to the deck (`actions.reads_only`):
they leave its cached state document standing, so Bosun's hook before every message costs
the deck nothing.

**Ending one.** Bosun takes it, works it, and resolves it one of four ways: fixed (no code
change), filed (a personal card with its repo, named with `--card`: Bosun files it with
`kb create --space personal --repo keel --from <the card that asked>` in builder mode and
builds it in its next batch; until c-593 it was a console card), declined, or escalated (the user's
to decide; raised as an ask, below). Every resolution carries a gap tag, a short slug Bosun names
and reuses (`unlisted-repo`): `kb console gaps` lists them and `resolve` says when one is
new, so BO-6's recurring-gaps list counts one gap under one name. The card that asked gets a
note ("r-12 fixed by Bosun: ..."). Its block stays: lifting it is the user's, or a repair when
Keel wrote it ("Repairs", below).

The state document's `console` entry carries `requests` (the open and taken rows),
`journal` (the last fifty request events) and `counts.requests` (the open ones: the header's
grey number and the tab's count), all read from the board where it lives
(`deckstate.console_entry`).

## Asks

An ask is a question Bosun has for the user, as a record (c-521, `keel/asks.py`): a row in the
board's fourth table, `asks`, numbered `a-N`. Every move on it is an `ask` event under that
id and, when it is about a card, on that card too. Three kinds: an **approval** (something on
`bosun/memory/needs-you.md`, a deploy), a **decision** (a real choice), an **escalation** (a
design change). Two to four options, lettered A to D in the order given: A is Bosun's
recommendation by position, so it cannot be anything but first, and each option carries
`does`, exactly what Bosun will do.

Each sub-verb of `kb console` for asks, who may run it, and what it does:

| Verb | Who | What it does |
|---|---|---|
| `kb console raise "<q>" --kind K --why W --option "label\|does" ... [--card <id>] [--file "letter\|title\|brief\|autonomy" --file-repo <key>\|none [--file-kind research]]` | `bosun`, `human` | files `a-N`; `--file` only on an escalation, naming the personal card that option files and, as its last field, its autonomy (`attended` or `autonomous`, c-584; a brief that names the other, or names one the field leaves out, is refused), `--file-repo` the repo it builds in, and `--file-kind` the kind it is marked |
| `kb console asks [--all]` | anyone | the open ones; `--all` adds the closed |
| `kb console show a-N` | anyone | the row, its options and its moves |
| `kb console answer a-N <letter> [--words W]` | `human` (tap), `voice` | answers it, the user's words beside the option |
| `kb console answer a-N --words W` | `human`, `voice` | no option: closed as **redirected**, none of its options done |
| `kb console answer a-N <letter> --by chat --message M` | `bosun` | Bosun's reading of the user's chat answer, the user's exact message kept beside it |
| `kb console withdraw a-N --why W` | `bosun` | the question no longer stands |
| `kb console pending`, `claim`, `confirm`, `unclaim` (`--ids`, `--via wake\|hook`) | the drain (`confirm` also Bosun's hook) | the answers not yet told, the lease on them, and the delivery |

**Three channels, one record.** The actor decides the channel: `human` is a tap (the
Bosun page, or the user's terminal with the user's token), `voice` is Harbor (with the user's token as well: a
bare `--actor voice` is anyone's to type, so it is refused), `bosun` is the chat. The user
answers in the chat in plain words (decision BO3-1, the user's answer): Bosun records its reading
with `--by chat` and the user's exact message, says in one line what it recorded, and only then
acts. Anyone else is refused. An answer to an ask that is not open is refused with how it
closed.

**An escalation files only on the user's answer.** Its `--file` option carries a title and a brief;
answering THAT option files a personal inbox card, `--from` the ask's card, inside the same
write, signed by whoever answered. Bosun never files an escalation's card itself (it files
its own queue's cards in builder mode, a different thing).

**The card it files names its repo, settled at raise (c-550, r-21).** `--file-repo <key>`
states it; without it, the `--card`'s repo is taken; with neither, the raise is refused.
`--file-repo none` files an errand on purpose, even when the `--card` has a repo. The repo is
checked against the personal space's keys (`kb repos --space personal`, create's own
`cli.refuse_unknown_repo`) before the ask exists, and written on the option as `files.repo`
(`""` for an errand) with `files.repo_from` (`stated` or the card's id). Every place the user reads
the ask says where it builds, in `asks.where`'s words: the Needs you option row
(`files a personal card in keel: <title>`), `kb console asks` and `show`, and the voice's
digest (`deckdigest._files_line`, the same words, since that file imports nothing from
`keel`). An ask raised before this carries no `files.repo`: it says `repo from its card` and
files from its card, as it did. c-541, filed from a-15 with no `--card`, landed with no repo
and blocked as an errand: that is what this closes.

**It can arrive marked research (c-553).** `--file-kind research` on the same escalation
writes `files.kind` on the option, and the user's answer creates the card with `options.kind =
research`, so its Approve outcome closes it with nothing landed (r-24). `kind` stays the user's to
change after create (`board.HUMAN_ONLY_OPTIONS` fences `set`, not create); setting it here is
the user's act, since it is the user's answer to the option that showed it. Every surface above adds
`, marked research` to where it builds (`asks.where_marked`). `research` is the only kind
it takes: the others mean something only to the work adapter.

**Telling Bosun.** A chat answer is told as it is recorded (the user's message is the turn). A tap
or voice answer waits, `delivered_at` empty, and reaches Bosun one of two ways, whichever
comes first. Each takes a LEASE on it (`asks.claim`, `claimed_at`) and records the delivery
only once Bosun has it (`asks.confirm`: the wake returned, or the hook printed). A claim
nobody confirms (a lost reply, a drain that died) runs out after `asks.LEASE_MINUTES` (10) and
the answer is told again, marked as possibly told already, so an answer is repeated at worst
and never lost:

- **The wake.** The drain (`drain.answers_upkeep`, [the drain](30-drain.md))
  claims the waiting answers and calls `consolewake.wake`, under the tap lock: an idle Bosun
  gets a MESSAGE into its live session (`relay.tell`, c-530) that names the answers and
  nothing else: "Keel drain: the user's answers to a-31, a-32 are recorded on the board and not yet
  read by you; `kb console hook` reads them." Bosun reads them by running `kb console hook` (`bosun/memory/asks.md`), which
  takes the wake's claim, prints the words and confirms them. The drain's claim is a lease on
  POINTING, not a telling: it stops the next pass sending again while Bosun reads, and when
  nobody confirms it runs out and the answers are pointed at again, at most
  `asks.POINTS_MAX` (2) times, counted on the board from the ask's `pointed` moves (an
  `unpointed` one takes back a wake that sent nothing); after that, and for any
  answer a hook has held, they wait for the hook atop the user's next message (the hook takes a
  wake's claim; `again` marks only a hook's earlier claim, and
  the wake never takes a row a hook has held, so that mark is never lost).
  No command sends a cross-session message, so a one-shot `claude -p --model haiku --tools
  SendMessage --name keel-drain` carries it, under personal's config dir and without Bosun's
  key, and its stream is checked rather than its words: exactly one SendMessage to `Bosun`
  with the message unchanged, and a result saying it reached a session on this machine.
  Nothing is stopped or resumed, so the session id and the app link never move. Probed
  2026-09-26 on 2.1.283 (`state/cards/c-530/probe/`): a message ran a turn in a
  live `--remote-control` session with the same pid and one link after, and the
  real Bosun took a relay's message unchanged, at about $0.03. The same probe found the
  relay model OBEYING an instruction inside a longer message instead of sending it, twice in
  three, which is why the message is ids and fixed words only (the paused houses' one too,
  `pausewake.wake_prompt`, with no title and no block text a house wrote). The wake it replaced
  (c-521: stop an idle Bosun, then `claude --resume <id> --bg "<prompt>"`) came back as a
  copy without remote control, which broke the user's app chat; that is why it is gone.
  A working, stopped, stuck or never started Bosun is not woken: the answers wait for the
  hook atop the user's next message (after the user's Start, for a stopped one). Two live sessions named
  Bosun are never messaged (the message goes by name). A relay that certainly failed hands
  the answers back (`unclaim`); one that may have sent (a timeout, two sends, no result)
  keeps the claim, so they are never pointed at twice unmarked. Either leaves Bosun exactly
  as it was, writes the Journal, and is sighted (`drain:step:answer-wake`), which opens a
  request on its third inside the hour. After a failed relay every wake rests for
  `consolewake.BACKOFF_MINUTES` (15), read from the Journal, so a relay that keeps failing
  is not a paid model turn every 30 second pass. `wake_keeps_id` in `state/console.json`, the old
  wake's switch, gates nothing now and is dropped on the next launch.
- **The hook.** `kb console hook` atop the user's next message, or run by Bosun on the drain's
  message, claims every waiting answer, prints it, then the open asks, then the requests,
  and confirms the answers it printed.

Either way Bosun reads the same words, built from the row alone (`asks.told`): "The user answered
a-31 (Deploy k-7?) by tap: A, Yes, deploy. What A does, and all you do for it:
...", with the user's words beside it quoted, or for a redirect that none of its options is to be
done. `bosun/memory/asks.md` is how Bosun raises one and what it does with the answer.

**The card it is about needs the user** (decision BO3-3): `derived.ask` names the open ask, and
`needs_you` holds while it is open, so the crit border, the user's Attention list, the phone's
primary action ("Answer Bosun", which opens the Bosun page's Now at the ask, `/console#a-N`) and Harbor's
needs-you list all say so. `gate_since` is the ask's own time.

The state document's `console` entry carries `asks` (the open ones and the last ten closed),
`counts.asks` (the open ones: the header's red number and the tab's count), and the ask
moves in `journal` beside the request moves.

## What Bosun may do

What Bosun may write is `keel/authority.py`, an ALLOWLIST checked where the board lives: a
write it does not name is refused to `bosun`. With builder mode off ("Builder mode", below)
Bosun may block a card and repair one, and nothing else.

| Rule | Where it is enforced |
|---|---|
| `kb` verbs: show, list, needs-you, repos, tree, queue, lint, help, console, create, set, stage, approve, note, block, unblock, split, tested; every other verb is refused | `authority.refuse_verb`, from `cli.main` |
| create only a personal card, only in builder mode; nobody creates in the retired `console` space | `authority.refuse_create`, from `Board.create` |
| set a field, move a stage, split, note or unblock only a card it builds (a personal card in builder mode), outside a repair | `authority.refuse_set`, `refuse_move`, `refuse_note`, `refuse_unblock` |
| a block on any card, never marked (`--mark` is the drain's and the review gate's) | `authority.refuse_mark` |
| a gate only as in "The outcome gate", below: an outcome, in builder mode; a plan gate is the user's | `authority.gate_approval`, from `Board.approve` |
| its approve carries no words of the user's: a `said` on its gate route is refused | `actions.act_approve` |
| a repair (`--why`) on any card, each kind only as in "Repairs" below | `repair.refuse_repair`, from `Board._repair` |
| a relay only for its checked outcome (`land`); its house repairs act on this machine and relay nothing | `Board._relay` |
| no write to its own authority files while builder mode is off | the guard hook, below |

A personal card is Bosun's by its repo ("Keel cards on the user's board", below), never by a
switch.

## A paused house

The one card state that wakes Bosun (c-584, `keel/pausewake.py`; the user's taps that do are
"Telling Bosun", below): auto mode paused a house on
a permission prompt, on ANY card in any space. The drain blocks such a house, marked
`permission-pause` ([the drain](30-drain.md), "A house auto mode paused on a permission prompt"), and
the drain's pass (`drain.pause_upkeep`, after the answers' wake) asks the
board for the paused cards whose pause came after their last `wake` event:

| Verb | What it does |
|---|---|
| `kb console wakes` | the cards whose standing pause Bosun has not been woken for, then the cards with a tell it has not heard ("Telling Bosun", below) |
| `kb console woke --ids <card>@<event>` | the drain's record of a wake: the event it told Bosun about, so a pause recorded mid-wake is still told |

It tells Bosun through `consolewake.wake` (a message, idle only, never mid-turn), in ids and
fixed words only (`pausewake.wake_prompt`: "c-9 (auto mode paused its house on a permission
prompt)", never a title or the block's text), then records a `wake` on each card, so a pause
wakes it once. At most one wake a pass (`drain.wake_upkeep`): when the user's answers woke Bosun, the
cards wait for the next pass, since a Bosun just woken is not yet listed as busy. Bosun then
reads the block and raises an ask naming the card, with what it was denied and what the user can do
(`bosun/memory/builder.md`, "A paused house"); on a work card that is all it does. No
timers: a house that cannot tell it is stuck is Keel's to read from the harness, as the
permission pause is, or it stays a house-side gap. Until c-593 a card Bosun drove also woke
it at a staged plan or outcome, a block, a failed resume and the review limit.

## Telling Bosun

The second stranger run (2026-10-10) found two silences. Draft a connection filed a card at
assigned in Bosun's queue and nothing told Bosun, so it sat until the user nudged it; and
Approve plan on that card, which Bosun builds and which has no house, answered "no session
to resume". Since c-734 the user's tap on Bosun's own work is told to Bosun by the same wake
as a paused house, through the same `consolewake.wake`, its claim and its backoff; there is no
second channel.

- **What is told.** A card the page files for Bosun to work with the user: a repo's or a
  space's CLAUDE.md draft (`tiercards.open_draft`, on Add your repos and on Open a draft for
  Bosun), a flow draft (`flowcards.open_draft`), a connection draft
  (`packdraft.draft_connection`) and Import my Claude setup (`onboarding.import_setup`).
  And every gate tap on a card Bosun builds (`derived.bosun`): Approve plan, Send back (at
  either gate) and Approve outcome (`actions.gate_answer`, `actions.outcome_told`).
- **How.** Each records a `tell` event on the card (`pausewake.tell`, data `{what}`: `filed`,
  `plan`, `sendback` or `outcome`). `pausewake.wakes` lists, after the paused houses, every
  card whose newest tell came after the event its last `wake` covered (one query of the
  events table, `PENDING_TELLS`, so a done card's outcome tell is told too), and the drain's
  `pause_upkeep` sends them in the one message, ids and fixed words only
  (`pausewake.TELLS`: "c-2 (filed for you to work with the user)"), then records a `wake`
  on each. A Bosun that is busy, stopped or resting after a failed relay is told on a later
  pass; one that was told is never told again for that tap.
- **No house is resumed for a card Bosun builds**, whatever session it carries: the move
  lands, the tap is a tell, and the answer says "Bosun is told at once, or as soon as it is
  free" (`pausewake.TOLD`), which the deck draws as a plain sentence (`r.told`), never the
  error a missing session used to be. Bosun's own approval tells nobody.
- **At once** (review r1.F18): recording a tell asks for one ordinary pass,
  `keel drain --once`, started and not waited for, as Approve outcome's landing does
  (`pausewake.ask_pass`), and only where a drain serves this install (its kick inbox is
  held). That pass runs the same wake (`drain.wake_upkeep`), one a pass. A kick's carry
  (`drain.carry_pass`) runs no wake. A pass that is not asked for is no loss: the pass on
  the drain's clock tells it.
- **Wakes are spaced**: `consolewake.wake` sends nothing while the newest wake the Journal
  says went ("told ...", by the drain) is under `consolewake.SPACING_SECONDS` old, which is
  `relay.RELAY_TIMEOUT` (120 seconds), the longest a sent message takes to start its turn,
  while a Bosun just told can still read as idle. So two passes close together (the drain's
  own and one a tell asked for) land one message, and the second waits for a later pass.
- **Send back with "stay" is refused on a card Bosun builds** (r1.F16), in plain words and
  before anything is written: a discussion is a house's turn on the plan surface, and such a
  card has none. Its plan is talked over in Bosun's own session, so a separate "discuss"
  tell would only point there.
- **The page says it.** A filing's answer ends with the same sentence, and the connection
  draft's check says "Bosun has been told" once the wake has gone (`pausewake.told`).

## Repairs

The rule (c-575): anything stopping the board from behaving as it should is
Bosun's to fix, on ANY card, in every space, work included, without Bosun gaining a say in
what a card is. A repair is the ordinary verb with `--why "<what broke>"`
(`keel/repair.py`, an authority path; `keel/repairhouse.py` carries a house repair to the
house). Each is an `intervene` event signed `bosun` with `data.what: repair`, the kind and
the why, and that record is all: nothing counts repairs, since the three strikes an hour
went with driving (c-593). A held card (voice or drop-in) is refused. `--why` from anyone but Bosun is refused
(`repair.refuse_why`), and the deck carries it like every other flag (`actions.why_argv`,
`requests.argv` for `kb console`).

| Repair | Verb | Allowed only when |
|---|---|---|
| a path Keel reads | `kb set <card> plan_ref=<p> --why ...` (also `output_ref`, `options.worktree`, `options.worktrees`) | nothing else is in the set; a ref is an absolute path to an existing file inside that card's own `state/cards/<id>/`, directly in it, under the same file name it names now (never from an empty ref: a plan_ref set from none would open the user's plan gate, a move rather than a path), never an `http` ref; the `set` event carries `repair`, so it does not reopen the plan wait (`Board.OPENED_BY`); a worktree is an existing directory with `.git` that normalises the path the card already records: the same directory name, for `options.worktrees` the same repos (keys), none added or dropped, and each tree a worktree of its own repo's checkout as the install's `config.toml` names it (`options.worktree` the card's first repo), by git's common directory, asked with every `GIT_` variable stripped so an inherited `GIT_DIR` cannot answer for every tree (`repair.owner_facts`, `repair.git_env`, c-588; c-585: a work card names every repo's tree after one branch, so a name alone let two repos' trees swap) (`repair.refuse_trees`) |
| a house whose block Keel wrote | `kb unblock --why`, `kb console resume --why`, `kb console retry --why` (both refused without `--why`) | the card's standing block is marked Keel's mechanics (`--mark mechanics`, `data.mechanics`, which only the drain and the hook may write: a house that failed to start in `house.py`, a review round that could not start in `shipping.py`, a landing that merged and did not move in `landing.py`), is the drain's failed resume (never Bosun's own: with no strike limit, a repair that failed and re-marked the card would loop, so Bosun's failed resume is the user's, c-593 review), or is a house's `kb block --keel` (Bosun's own `--keel` block is not one, `repair.KEEL_REQUESTERS`). Every other block is the user's: a house's question, the user's block, a drain block without the mark (a failed merge, a quiet house, a card with no model; the last two pinned at their writers, `drain.block_quiet` and `house.require_model`, c-585), a permission pause, a login hold, the review limit. A repair resume carries NO words: the house hears the plain resume line (`prompts.RESUME`, `repairhouse.resume`) and the why stays on the card; `repair.refuse_words` refuses words in `Board.repair`, inside the fence. A busy house is refused before the repair is recorded (`repairhouse.refuse_busy`), and a retry keeps `authority.refuse_retry` (never at the user's plan gate, never before the user assigned it) |
| a replayed move | `kb stage <card> <stage> --why` | the stage is the one the board already records and one of `repair.REPLAY_STAGES` (assigned, planning, building: no landing or pull request waits there; planning only while the user's plan gate is not open), with no `--plan`, `--output`, `--relay` or `--note`, and the stage rules pass (never a tracking card). A replay (`Board._replay`) checks the move again and signs it: its `intervene` event is the whole record. It writes NO `stage` event and changes no field or option, because every reader that measures a move (the landing guard, a gate's age, the review trip, the drain's quiet streak) reads `stage` events, and a replay that looked like a move withdrew the user's approve or reset those clocks (reviews 1.F1, 2.F1, 4.F4). So it re-runs nothing: it is a signed record that the move was checked |

**Where the files are.** The path facts are read where the card's files live
(`repair.repair_facts`), on this machine: every house is this machine's, so they are read
from the disk. A house repair is carried out here too: `repairhouse.resume` resumes the
house itself and `repairhouse.retry` puts the card back to assigned for the drain. Until
c-648 both asked a door whether the card's house was on another machine and relayed to it;
the door module, the relays and Bosun's leave to write them (`resume`, `start`) are gone.

**Still refused, whatever the `--why`:** a gate (`authority.gate_approval`), a plan's
decisions, any other field (title, brief, autonomy, repo, model, topic, parent, after, kind,
any other option), and any verb that reaches a tracker, code host, chat or mail (none is on
its list).

## The outcome gate

c-526, and since c-593 builder mode's alone. Bosun passes a gate by **one route** (the user's D3):
its `kb approve <card> outcome --checked "<what>"` runs on the board directly as `bosun`
(`cli.bosun_gate`, once its key checks), never through the deck's page: it closes no voice
conversation and forces past no hold (a held card's gate is refused to Bosun), and its notes
are signed `bosun`. `authority.gate_approval` refuses unless the card is
personal, builder mode is on, the gate is the OUTCOME (a plan gate is the user's: an attended card
is how the user asks to see a plan first), the card is not held, and `--checked` says what Bosun
checked. A work card's gates are the user's whatever else holds.

`cli.cmd_approve` reads the outcome where the board lives (`authority.outcome_facts`: the
card's `context.md` linted, the newest review pass, the branch and its sha) and
`authority.outcome_refusal` refuses, each with the reason, unless:

- the card's repo has an integration branch (`[integration]`, the user's D4): where approving would
  put it live, the outcome is the user's;
- the integration branch is not the trunk the machines run;
- the outcome lints clean and no review pass is still open;
- the review stamp covers the branch as it is (`review.gate.covers` on the worktree it lands:
  a closed pass or a fix check moved it to this head), so no commit lands under Bosun's
  signature unreviewed;
- there is a branch sha to pin.

The Risk, open-findings and fence checks (`OUTCOME_FENCE`) were for driven and console cards,
and went with them in c-593; builder mode had already skipped them (the reason:
bulk building needs Bosun to land changes to its own authority and the deploy's code), so
main moving only on the user's deploy is the check left on such a change.

Passed, it is NOT a merge: `Board._approve_as_bosun` writes the note signed "approved by
bosun, in builder mode" with what it checked, and a `land` relay for this machine's drain,
pinning the branch's sha (the only `land` relay Bosun can write; `kb relay` refuses it), and
`kick.after_verb` asks the drain for a pass. The landing worker lands it on
`next` exactly as it lands the user's queued tap ([cards and gates](10-cards-and-gates.md), "The
integration branch"), and `kb land` accepts a relay that is the user's or carries Bosun's checked
approval. Main moves only on the user's deploy ask ([the drain](30-drain.md), "Deploy").

**The auto-mode classifier.** Bosun's settings allow its own `kb` verbs by rule
(`console.KB_ALLOWED`), so whether it may pass a gate is decided by builder mode and the
checks above, not by the classifier.

**Its own authority.** A PreToolUse hook on Bosun's session, `keel console guard`
(`console.guard_verdict`), denies Edit, Write, MultiEdit and NotebookEdit under
`authority.AUTHORITY_PATHS` (`bosun/memory`, `state/console`, `keel/authority.py`,
`keel/console.py`, `keel/consolehandoff.py`, `keel/consoletaps.py`, `keel/repair.py`,
`keel/repairhouse.py`) and under `authority.INSTALL_AUTHORITY_PATHS` in the install
(`memory`, the whole memory root with its `.git`, c-722 and r1.F2: Bosun's memory moved
there and its guard went with it, and the repo's history is the memory as much as its
files), and a Bash command that names one and writes; the same paths are denied to the
editing tools by rule (both lifted for the superuser builder, below; an
install's builder keeps both, `console.builds_itself`). The memory roots are matched in a
Bash command by any spelling as well (`authority.bash_hits`, r1.F2): a word that resolves
(absolute, `~`, `$HOME` or `${HOME}`, the value of an `--opt=` word, or relative: to Keel's
root always, and to the session's working directory from the hook's payload as well,
`authority.relative_bases`, which only adds a reading and never exempts one) to the memory
directory, inside it, or to a directory that holds it below its base (`rm -rf bosun`), with
a writing verb (`console.WRITES`, or `console.GIT_WRITES`, a git write with
its options before the subcommand, `git -C <memory> reset`), or with a redirect when the
word is absolute, follows `cd`, or is the redirect's target. On top of it the install's
Bosun memory is matched as text (`authority.text_hits`, `INSTALL_TEXT_PATHS`, exactly the
match it had before r1.F2): a write whose text names it is refused, however the rest is
spelled (`p=...; echo x > $p/f`, `cd <install> && ...`), with no exclusion by working
directory or by spelling, since each exclusion tried opened a hole (the lesson of c-723).
The cost is accepted: in Bosun's clone of the memory repo, `<install>/builder/memory`, a
shell write that spells an absolute path through the clone is refused as well, and so is a
relative `git checkout -- bosun` there (Keel's root is always a reading, and its `bosun`
holds the checkout's memory). A memory card is built with the editing tools on the clone's
files (their deny is path-precise, so the clone stays editable) and git with relative file
paths: `git add -A`, `git commit -m ...`, `git checkout -- bosun/<file>`, `git switch -c`
all pass. **A stated boundary (r1.F10):** a command that makes a link to or from the memory
(`ln`, a writing verb, naming its path) is refused, but a write through a link made
elsewhere, or earlier, names neither the path nor its text and is not seen, the same
boundary as c-723's "a `kb` defined earlier". So `git -C <install>/memory reset --hard`, `rm -rf
<install>/memory`, `cd <install>/memory && echo x > f` and a write to its `.git` are
refused, and so are the same forms on the checkout's `bosun/memory`; `git -C
<install>/memory log` and a read pass. Every house is denied the install's `memory` root as
well (`house.memory_deny`): its editing tools, and a Bash command naming it, the way
`secret_deny` holds the secrets. It sits outside every worktree, so a house changes it on a
card and never by writing the live files or rewinding their history. The editing
tools are refused only under the code Keel runs and the install's own memory
(`authority.authority_hit` resolves the path against Keel's root, then the install's),
so an install's builder changes these files in its clone with the editing tools, on a card;
a Bash command is matched by the path's name alone, so one that names such a path and
writes is refused anywhere, the clone included. Like every deny it
is a speed bump for a same-user shell. The board's refusals to actor `bosun` are what holds
by mechanism, and Bosun runs as the user who holds the shared key its own is derived from,
so nothing in the operating system separates it from the user ("The builder", below).

## Builder mode

`[keel] bosun_builder` (off by default; `Config.bosun_builder`, in `Config.switches`, so the
Board reads it as `Board.builder` where the board lives). What follows is the superuser
builder's, the one an older checkout's `keel.toml` names. A new install's builder is Bosun:
its first run says "Meet Bosun, your builder" after the user picks its form (Full or Guide),
and how that builder works is "The builder", below, a section name and not what the page
calls it (c-729). While Keel is young, Bosun builds
and lands Keel's own fixes itself rather than bringing each one to the user. It changes these
things, and only on personal cards:

- **The board.** On a personal card whose worker is not a house ("Who works a card",
  below; `authority.builds`) Bosun may create it (`authority.refuse_create`), set its
  fields and archive it (`refuse_set`), move its stage and split it (`refuse_move`), note it
  (`refuse_note`) and unblock it (`refuse_unblock`), with no intervention recorded and no
  limit. A voice or drop-in hold still stops an unblock and a gate, and a stage move still
  cannot pass a gate (an attended card leaves planning only through `approve plan`, which is the user's).
- **Its queue** (`views.bosun_builds`, `derived.bosun`). A personal card on a repo Bosun
  builds (`[builder] repos`, "The builder" below) is Bosun's to build unless its **worker**
  is a house (`options.worker`, c-645, "Who works a card" below): `views.startable` is false for it, so the drain never starts a house on
  it and `kb queue` never says it starts next. Nor does a pass of the drain resume or wake a
  house session such a card still carries (c-647: a start made by accident before Bosun
  took the card left one, and the drain put that house back to build beside Bosun); the card
  says so once, and what still reaches that house is the user's own tap or a rotation that was
  asked for ([the drain](30-drain.md), "The pass", step 3). A personal card with no repo (research, a
  plan, an errand) stays a house's. Bosun moves its own card to done from any stage but
  shipping once it has landed it (`Board._refuse_stage`, "landed by Bosun"), with a note
  naming the sha on `next`. A request it resolves `filed` is such a card ("Requests").
- **The gates** ("The outcome gate", above). A personal card's outcome is Bosun's to land on
  the integration branch; its plan gate stays the user's.
- **Its session** (`console.settings`, rewritten on every start). The guard
  (`console.guard_verdict`) no longer refuses a write to `AUTHORITY_PATHS`, and the editing
  tools' denies on them (`console.authority_deny`) are left out, so Bosun edits its own
  memory and authority code, in a worktree or in its clone. Its settings file (its key)
  stays refused. `console.builder_allow` allows the git and test steps of building
  (`BUILDER_GIT`, `BUILDER_MAKE`), never a push, merge or rebase, so the auto-mode
  classifier does not stop them. The denies on work credentials, work tools and the shared
  key are unchanged.

Work cards, repairs and the deploy are exactly as they are with the switch off. Turning it
off (and restarting Bosun, for its settings) leaves Bosun a block and its repairs.

## The builder

c-619, c-621 (a-94: one builder for everyone, no second user; unfenced,
below). On a new install this builder is Bosun, and the setup page names it so: Choose your
builder picks its form, and the next step is Meet Bosun. `[keel] bosun_builder` turns building on; the `[builder]` table says
what Bosun builds (`keel/builder.py`), read where the board lives as two switches and a
scope: `Board.builder`, `Board.superuser` (`builder_superuser` in `Config.switches`, never on
an install) and `Board.builds`, the repo keys the builder builds (`builder.repos`). For the
builder `views.bosun_builds` is a personal card on one of `[builder] repos`, and a personal
card on any other repo is a house's; for the legacy superuser it is every personal card
with a repo, exactly as before c-619 (a `projects_dir` one and a `new_project` included).

### Who works a card (c-645)

Every card's worker is Bosun or a house, and the user sees it before it is created.

- **`views.bosun_eligible`** is the rule above: builder mode, a personal card, a repo Bosun
  builds. **`options.worker`** (`house` or `bosun`, `views.WORKERS`) is the user's choice, and
  **`views.bosun_builds`** is eligible AND a worker that is not `house`. A card with no worker
  gets the rule's answer, so every card from before c-645 is unchanged. That one function is
  still the gate of the drain (`startable`), Bosun's queue (`derived.bosun`) and the user's
  approvals (`Board._approve_as_bosun`).
- **`bosun` is refused on a card Bosun may not build** (`Board._refuse_worker`, at create and at
  set): the work space, builder mode off, or a repo off `[builder] repos`. A value outside
  `WORKERS` is refused. `WORKERS` is a list, so a later worker (the user's own, "you") is one more name.
- **Only the user sets it**, and only before anything starts: `options.worker` is in
  `HUMAN_ONLY_OPTIONS`; at create and split only the user's actors may name one (`WORKER_SETTERS`:
  human, voice, the talker, as `bosuncards.HIS_ACTORS`); and `Board._refuse_worker_move` takes
  a change only at inbox or assigned, with no session, no drain's claim, and not on a
  tracking card (each slice has its own; archived slices do not count). The drain never starts a claimed card that is now Bosun's (`claimed_unstarted`).
- **A card made from a house's card is a house's** (`Board._inherit_worker`): a slice, and a
  `--from` card, carry `house` unless they say otherwise.
- **Bosun never acts on a house's card as its own**: `authority.builds` (its set, stage,
  split, note and unblock) is false for it, as `bosun_builds` is.
- **Where it shows.** `derived.worker` and `derived.worker_eligible` on every card. The new
  card form's Worker row ([the deck](40-deck.md), "The card form"). The pane's details:
  "Bosun: you approve its plan and outcome", "Bosun: approves and lands it on next; the
  deploy is yours" (superbuilder; `next` is the card's own landing branch, read through
  `K.landsOn`, and no branch is named for a repo with none), or "a house: you approve its gates". Give to a house and
  Give to Bosun (`worker`, the Card group). `kb create --worker house|bosun`. The state's
  `config.builder` (`deckstate.builder_facts`: on, the repos, whether Bosun lands) is what the
  form reads.

| `[builder]` key | Default | What it decides |
|---|---|---|
| `superuser` | `false` | the legacy superuser (true only in an older checkout's own `keel.toml`); refused on an install |
| `repos` | `["packs"]` | the repo keys the builder builds: `packs` plus any personal repo the user lists (the import carries keel and harbor, `importconfig.builder`) |
| `mode` | `"auto"` | `auto`: Claude Code's auto permission mode, its classifier reviews what no rule settled. `bypass`: the superbuilder, Claude Code's `bypassPermissions`, nothing asks or reviews (`builder.PERMISSION_MODES`, `builder.permission_mode`) |

**The two forms the user picks from** (c-678, the first-run design's decision `forms`). The
first run's Choose your builder names the two modes for a person: the **Guide builder** is
`auto` and the **Full builder** is `bypass` (`firstrun.FORMS`). Nothing is preselected: a new
install's `config.toml` names no `mode` (the example carries the line commented out), the
step is open until the user's pick writes one, and until then the builder runs as auto, the
default. An install whose config already names a mode is read as having chosen it
([onboarding](89-onboarding.md), "Choose your builder and Meet Bosun").

**Choosing Full is the acceptance of bypass mode** (c-729). Claude Code asks once per config
dir before a session runs in bypass, and a background session cannot answer it, so on a
fresh install Bosun in bypass did not start until the user ran Claude by hand to accept.
The Full card already explains the risk, so the pick is the answer: every settings save that
touches `[builder] mode` or `[keel] bosun_builder` calls `builder.record_bypass` on the
config as saved, which writes `skipDangerousModePermissionPrompt: true` into the user
settings of Bosun's config dir (`<install>/claude/settings.json`) while the builder is the
Full builder (`builder.bypass_chosen`) and takes the key out otherwise (Guide, or builder
mode off), keeping every other key. It touches only a Claude folder inside the install
(`builder.owned`, r1.F1): a personal space pointed at the user's own `~/.claude` is never
edited, and a `settings.json` that is a link is left as it is. The key is `builder.BYPASS_ACCEPTED`, read off Claude Code
2.1.295: a background session in bypass needs it in the user settings, and neither
`--settings` nor `settings.local.json` counts. A session started with
`--dangerously-skip-permissions` in a config dir carrying it opens with no warning.

**One builder on an install, running as the user.** Bosun on an install is the builder below.
It has the user's reach (their files, their network, their tools), in auto mode by default and
in bypass when the user sets `[builder] mode = "bypass"`. There is no sandbox:
one PreToolUse hook keeps it out of a live checkout, a second (`keel console guard`, "Its own
authority" above) keeps it off its own authority, a few deny rules keep it off credentials
and off pushes to the integration branches, and the board's own rules decide what it may do
to a card. **That is the whole boundary, and none of it is operating-system separation**: the
builder is the same Unix user as Keel, so the user's token, the shared key and the board's file are
within a shell's reach. The board's refusals to actor `bosun` (a deploy, a gate not its own,
a relay other than a checked `land`, a verb off `authority.VERBS`, a card it does not build)
hold for a `kb` that presents Bosun's key; the hooks and the denies are rules for Claude's
own tools, speed bumps a shell could spell a way past. Its memory says so in those words
(`bosun/memory/authority.md`): a refusal is an answer it brings to the user, never something to
get past. This was already so before c-648 for an install's builder; only the superuser on
the box had a Unix user of its own. There is no superuser switch on an install: `[builder] superuser = true` there is
refused at Start and in `keel doctor` with one line (`builder.INSTALL_SUPERUSER`, which says
to set `[builder] mode = "bypass"` instead), and `Config.switches` never carries
`builder_superuser` for an install, so the board scopes Bosun to its repos either way.

**The superuser** (the legacy builder: `superuser = true` in an older checkout's own `keel.toml`, which is
not an install). Builder mode exactly as above
("Builder mode", "Bosun's own user"): `[console] permission_mode` (bypass),
`crossSessionInbound`, its own authority writable, `builder_allow`, approving its outcome
onto `next`, `kb tested`, the git gate. Bypass does not fence the editing tools, so
its fence was Bosun as its own Unix user. That mode is retired (c-648), so `builder.refusal`
refuses the superuser every Start until its fence is decided ("Bosun's own user", below).

**The builder** (every install). It builds the repos `[builder] repos` names, each from its
own clone:

- **Where it runs.** The same session named Bosun (`console.py`), its config dir the install's
  `claude/`, there on every install (`console.configured`), started only by the user's tap. Its cwd is `<install>/builder/` (`console.cwd`),
  holding its own full clone of each repo it builds (`builder/packs`, `builder/keel`, ...),
  made with `--no-hardlinks` so no object file is shared with the live repo
  (`builder.ensure_clones`, from the personal repo of that key: by init, and by Start for a
  repo newly listed, before `builder.refusal` looks). Its origin is the live checkout, which
  it fetches from and never writes. Its card files go in `<install>/builder/cards/<id>/`.
- **Its session** (`builder.settings`, from `console.settings`). `--permission-mode` is
  `builder.permission_mode`: `auto` (with `--permission-prompts none`: the classifier reviews
  what no rule settled, and a refused action is skipped, never asked) or `bypassPermissions`.
  No `sandbox` block: it reaches what the user reaches. Each Start or Restart tap re-reads the `[builder]`
  table from the file (`consoletaps.fresh_builder`): the tap runs inside the deck, which read
  its config at its own start, so a hand edit of `mode` used to wait for a deck restart.
- **The live checkout hook** (`bin/keel-builder-guard`, `keel/builderguard.py`, first in its
  PreToolUse list, `builder.guard_hook`): it refuses, with exit 2 and one line, an edit
  inside a live checkout (`builder.live_checkouts`: KEEL_HOME, the code Keel runs, plus every
  personal repo's live checkout, plus every repo the install copied into its layout, in
  any space (c-678: Bosun reads the user's repos to draft their CLAUDE.md and never edits
  them); a path its clones lie under is left out, or it could not
  write its own clone). The list is made when its session starts, so a repo copied in
  later is guarded from its next Start. It holds in auto and in bypass alike, since hooks run in both, ahead
  of the classifier. For the editing tools (Edit, Write, MultiEdit, NotebookEdit) it resolves
  the target by `realpath`, every link in the existing part followed, and fails closed: a call
  it cannot read is refused. For Bash it is a speed bump and not a wall: each command is read
  with `shlex`, following `cd` and `git -C`, and a git verb that changes a repo run in a live
  checkout, or a write (`rm`, `mv`, `cp`'s destination, `tee`, `touch`, `sed -i`, a `>`
  redirect) to a path inside one, is refused; reading there is fine, and a line it cannot parse
  goes on. It is run by the deck's own interpreter by absolute path, so a `python3` missing
  from the hook's PATH cannot make it a non-blocking error.
- **Deny and allow rules** (`builder.deny_rules`, `builder.build_allow`). Denied: Read on the
  install's `credentials/` and on the user's own secrets (`builder.HOME_SECRETS`: `~/.ssh`,
  `~/.gnupg`, `~/.aws`, `~/.config/gh`, `~/.config/gcloud`, `~/.kube`,
  `~/.docker/config.json`, `~/.git-credentials`, `~/.netrc`, `~/.npmrc`, `~/.pypirc`,
  `~/.claude/.credentials.json`, macOS `~/Library/Keychains`), and
  the pushes it never makes (`builderauto.PUSH_DENY`: force, mirror, delete, a `+` refspec,
  main, master, next), which match a command's text and so are a speed bump too. Allowed: its
  board verbs (`kb create`, `set`, `stage`, `block`, `unblock`, `split`) and `keel board push`.
  Its reads of the user's `~/.claude` CLAUDE.md, skills, agents and commands, for the import
  ([onboarding](89-onboarding.md)), are not denied.
- **Its `autoMode` block** (`keel/builderauto.py`, `builder.auto_mode`): `environment` says
  what the install is (its clones are its workspace, their origins the live checkouts it
  never writes, `kb` and `keel` trusted, the deck and Voice on 127.0.0.1, where the secrets
  are); `hard_deny` adds to the built-in rules: pushing to main, master or next, any
  force-push, writing in a live checkout, reading or sending credentials, posting an
  action to the deck's page API as the user, and (c-678, since auto mode is the Guide
  builder) installing software on this computer, changing its settings or writing outside
  its own clones and card folders: it gives the user the command to run instead;
  `soft_deny` is the built-ins (`$defaults`);
  `allow` the built-ins plus building, testing and committing in its clones. **It rides in
  Bosun's own `--settings` file** (`console.settings_path`, 0600 beside the install's key),
  not in the config dir's `settings.json`: the classifier reads `autoMode` from the
  `--settings` flag too (2.1.287, 2026-10-03), so the personal houses that share `claude/` in
  auto mode never read the builder's environment, and no second config dir (and no second
  `/login`) is needed. In bypass the block is carried but no classifier reads it.
  **Both c-678 limits reach an install that was already set up**, not only a new one
  (approved, c-678 review): the hard deny on installing software, changing settings and
  writing outside its clones and card folders applies to every auto-mode builder from the
  deploy on, and the live-checkout guard is wider for both modes, since `builder.live_repos`
  now counts every repo the install copied, in every space, as a live checkout whose
  folder the guard refuses writes in. An install whose repos are attached where they were
  has no copied repo, so its guard list is unchanged.
- **Its `kb` reaches the board directly.** Bosun's `kb` opens the install's board itself with
  Bosun's key (`KEEL_CONFIG` in its env), as actor `bosun`, and the board's
  actor rules apply as for the superuser Bosun; `keel board push` works as Bosun too
  (`boards.ACTORS` includes `bosun`). Posting an action to the deck's page API is the one
  thing it never does: that acts as the user (a `hard_deny`, and the guideline in its memory).
- **In bypass it passes its own cards' gates** (`authority.BYPASS`, `builder_bypass` in
  `Config.switches` on an install whose `[builder] mode` is bypass, `Board.bypass`:
  the superbuilder does not stop to ask). `Board._approve_as_bosun` holds it to a
  card it builds (`views.bosun_builds`; bypass widens no scope, unlike the superuser), and
  `authority.gate_approval` lets it approve that card's plan (signed with what it checked;
  the card moves to building) and its outcome under the usual checks
  (`authority.outcome_refusal`: an integration branch that is not the trunk, clean lint, a
  review stamp on the branch as it is, a sha), queued as a `land` relay like the user's tap. So a
  packs outcome, which would go live at once, stays the user's, and main still moves only by the user's
  deploy. Those checks read its branch: in bypass `authority.outcome_facts` fetches it from
  the clone first (`merging.fetch_built`, as the user's tap does), so the lint reads the outcome at
  that tip (`planlint.card_tips` includes `refs/builder/<branch>`). In auto mode nothing
  reads it before the user's tap (without the fetch, every approval in bypass is refused
  with "read only when the user's Approve outcome lands it").
- **Its review, once per stack.** Its session starts with the review
  agents (`builder.review_agents`, the `--agents` a house gets) and their `SubagentStop`
  hooks with no card on the line (`builder.review_hooks`: `keel-review-stamp --bosun`). Its
  cwd is `<install>/builder`, which is no checkout, so the hook takes the card from the ONE
  card directory the agent's prompt names, only a card the builder builds, and the head from
  that card's prep (`stamp.bosun_review`). Prep records where each change starts
  (`base_sha`), and `gate.built_covers` counts a builder card reviewed when a complete pass
  Bosun ran from its clones has its tip as the head, or holds its tip and starts at or before
  where the card's change starts in the target. So one pass at the top of a stack of slices
  covers every slice under it, a branch off next on its own needs its own pass, and a commit
  after the pass is not covered.
- **What the board refuses it** (`keel/authority.py`): in auto mode Approve outcome ("landing
  is the user's tap", `gate_approval` without `superuser` or `bypass`) and its plan gate,
  always `kb tested` (`refuse_tested`), and a
  card on a repo outside its repos (`refuse_create` with its scope); `views.bosun_builds`
  scopes its queue. Its card reaches done only by the user's Approve outcome: the board's
  "landed by Bosun" move to done is the superuser's (`Board._refuse_stage`).
- **How its work lands.** Nothing lands without the user's tap. It stages review with its
  branch as the output; the user's Approve outcome lands it, onto the repo's integration
  branch when `[integration]` names one (keel: `next`; main moves only by the user's deploy tap,
  as for any personal card) and onto its trunk otherwise (packs, live at once). At the
  user's Approve outcome (the tap's question whether there is anything to land, and the
  landing; a branch that already landed under another card closes the card with nothing
  merged, c-773), `merging.fetch_built` fetches the branch from the builder's clone of that repo
  into its own ref, `refs/builder/<branch>`, of the live checkout (as the user; never a
  `refs/heads` ref), for any repo in `[builder] repos` (`merging.built_clone`; a card the user
  gave a house there lands its worktree's branch from the live repo instead, c-647), and only from a real clone
  (`builder.real_clone`: a real directory and `.git`, no link or gitfile, resolved once under
  `<install>/builder`, `builder.clone_for`); the merge takes that ref and is the usual one.
  The branch is the one its outcome names (`merging.bosun_branch`, c-647), and only when
  that word is a branch of the clone (`refs/heads/<name>`): never the branch of a worktree
  a house left on the card, never a bare sha, a revision spelt off a branch, the target
  or the trunk. An outcome that
  names no such branch is refused with what to do (`kb stage <id> review --output
  <branch>`), on the superuser's cards too, read in the live repo
  ([cards and gates](10-cards-and-gates.md), "What Approve outcome publishes").
  **A conflict is Bosun's to merge.** When the target moved and the merge conflicts, the
  card goes back to building with a note naming the target and the branch
  (`landing.bosun_merges`, by the landing worker and by the tap alike); no house is
  resumed, `options.merging` is not set, and the note, the receipt (`landing.bosun_why`)
  and the deck all say the card is "waiting for Bosun to merge" it, never that a merge is
  under way. Nothing wakes Bosun for it: its wakes are the user's answers and a paused house
  (`consolewake`), and this is neither, so the note on the card is how Bosun and the user learn
  of it.
  Only Approve outcome fetches it (`branch_placed` with `fetch`, from `branch_head` pinning
  the user's tap and `land_card`): before it, the branch is not read, and the merge queue's pre-run
  skips the card (`landing.pre_run_one`, `landing.heads`), so nothing of the builder's runs
  unapproved. After it, Approve outcome runs that card's code as the user only through the
  repo's `[tests]` entry (keel's `make test` on the merged tree); init configures none for
  packs. The drain re-execs when the packs repo's head moves, or the head of a pack cloned
  into the packs folder (`drain.packs_moved`, c-740), and a
  merged pack is live on the next deck and drain restart.
- **May it start** (`console.refuse_builder`, at every Start). First a personal config dir
  this Unix user owns (`console.other_owner`, "Bosun's own user" below), whatever builder
  mode is: `keel doctor` says that sentence as its own `bosun:` line wherever the config
  has a Bosun (`doctor.bosun_owner`), and the builder's readiness row gives it as its why,
  both with builder mode off too; with builder mode on the doctor's `builder` line is not
  ready either and points at the `bosun` line (`doctor.OWNER_FIRST`), so the sentence is
  printed once. Then `builder.refusal`, which `keel doctor` shows as its
  `builder` line and the readiness row as its why, with builder mode on: an install with
  no superuser, a known `[builder] mode` (`auto` or `bypass`; an unknown one is refused with
  the choices), and its clone of each repo (made first by Start where a live checkout is
  there); each refusal is one line with its fix.
- **Its memory** adds `bosun/memory/in-app.md`, read last, which says what is different for
  it; the rest of builder.md is the superuser's. It holds the working pattern as guidelines,
  not mechanism: a branch per card in its clone (`bosun/c-NNN-<slug>`), big plans as tracking
  cards (`kb split`, or `kb create --parent` and `--after`), subagents for parallel slices
  each on its own branch with Bosun reviewing the result, never push main, master or next,
  never post an action to the deck as the user.
- **The Bosun page badge** (`builder.status`, `modeLine` in `app/ui.console.js`) says
  "Builder, auto mode" or "Builder, bypass" and the repos it builds; it has no sandbox or
  network line.

**Retired (2026-10-03).** A fenced builder (Claude's sandbox, a door of its own
with scoped verbs, an edit allowlist, a probe script, a clone fence restore, a
host allowlist and a debug mode) costs the user, for every gap in the fence (a door missing a verb or a field),
a round trip, when they have an unfenced Claude a terminal away anyway: the fence guarded
against the session rather than against accidents. So it is gone: the door
(`[builder] port`, its verbs, the carry of card files), the sandbox and its prerequisite check,
the proxy path in `kb`, the probe, the fence restore and the edit deny lists are gone; the
live checkout hook, the credential and push denies and the board's own rules stay. What the
same day added stays true: the deck's listen backlog ([deck](40-deck.md)), `kb stage` sending
`sync` only when set, and the board
letting the user or Bosun move an attended planning card back to inbox or assigned
(`board.QUEUED`, [cards and gates](10-cards-and-gates.md)).

## Keel cards on the user's board

c-592. A personal card is one of two things. **With no repo** it is research, a plan, an
errand or a capture: a house does it and writes the result, and no code pipeline applies
([the deck](40-deck.md), "Research on the deck"). **With a repo** it is a Keel card, Bosun's
to build ("Builder mode", above). The user's personal board labels it and says where Bosun has it;
whether the board shows it at all goes by WHO FILED IT, not by its autonomy.

`keel/bosuncards.py` sets `derived.keel_card = {filed_by, state, shown}` on every card with
`derived.bosun`, where the deck builds its state (`deckstate.build`), read from the board as
it is, nothing kept:

- **`filed_by`** is the actor of the card's `create` event: `him` only for the actors that
  are the user (`bosuncards.HIS_ACTORS`: `human`, which the deck and the user's CLI sign as, `voice`
  and `talker`), and `bosun` for every other filer: Bosun (including when the user asked Bosun
  to), a house, the drain, the cli, the doctor.
- **`state`**: `plan` (the user's plan gate is open, "plan waiting for you"), `queued` (inbox,
  assigned), `building` (planning to shipping), `next` (done, landed on `next`, not live)
  and `live` (its sha is on main). Next against live is read from git, the drain's own
  source for what a deploy ask carries (`deploy.repos`, `deploy.carried`): a done card
  whose landing merge (subject ending `(c-N)`) is on the integration branch and not on the
  checkout's trunk is on next; any other done card is live. The log is read once per
  (repo, trunk sha, next sha), memoised in process, so a state build costs a few
  `rev-parse` calls, not one per card. Only a done card that is not archived asks; an
  archived one reads live. A repo with no integration branch is live once done.
  **The fallback**, for a repo not checked out on this machine: the deploy asks (`deployask.places`, the same asks and moves
  as Shipped's `deployask.shipped`). A card an open ask carries, or one answered and not
  yet deployed, is on next; one a deployed ask carries is live; one no recent ask names is
  on next when it was done after its repo's newest standing ask was raised, and live
  before it. A withdrawn ask says nothing.
- **`shown`**: a card that needs the user (`derived.needs_you`: the user's plan gate, an open ask, a
  hold, an outcome gate) always; otherwise a card the user filed until it is live, attended or
  autonomous, and a card any other actor filed never: it lives on the Bosun page. A shown
  card at done (on next) travels in the deck's live part (`deckstate.in_done_part`), so the user's
  board shows it without Include done; the user's card gone live comes back with Include done, as
  a done card.

On the deck ([the deck](40-deck.md), "A Keel card on the deck") a Keel card carries the iris
**Keel · Bosun** label (`K.keelChip`) wherever it is listed, and Bosun's state in place of
the house, plan and outcome words. Its pane is **Bosun's view** of it: the label and the
state, the batch and branch (`options.bosun`), the sha Bosun named when it moved it to done,
who filed it, and Open the Bosun page (Now when it waits on the user, else Queue). A Keel card
has no house, so the pane draws no house control (Open in Claude app, Talk, Resume, Rotate,
Drop in, Logs); a held one offers Unblock only and the Bosun page.

## Bosun's own user

**Retired (c-648).** Bosun runs as the user Keel runs as, under the personal space's config
dir, from Keel's root (an install's builder from its clones). Until 2026-10-01 the superuser
Bosun ran on the box as its own Unix user, `bosun`, in `bypassPermissions` mode, and the
operating system was its fence: that user could not read the user's token, the shared key or the
board's file, and could not write the live checkout, so its `kb` reached the deck over HTTP.
Keel has had no board over HTTP since c-622, and c-648 took the mode out of the console
module. The `[console]` keys that made it (`config_dir`, `checkout`, `board_url`) are ignored
and named in the config's warnings (`keel/oldconfig.py`), which `keel doctor` prints;
nothing writes Bosun's settings or reads its transcript as another user; and
`bin/keel-bosun-user`, which set the user up, only says it is retired.

**What that leaves the superuser builder.** Its own Unix user was the fence of `[builder]
superuser = true`. The reason was measured 2026-10-01 (c-619): in bypass mode
permissions.deny rules DO hold and Claude's sandbox fences Bash, but the Write and Edit
tools are NOT fenced by the sandbox, so the editing tools could write anywhere the user can.
With that user retired, `builder.refusal` refuses a superuser config at every Start, in one
line (`builder.SUPERUSER_UNFENCED`: it does not start since c-648, until its fence is
decided); the builder's readiness row says the same, and so does `keel doctor` where the
config has a Bosun. What fences the superuser now is not decided: that is the user's, on a card of its own.

What the mode left in the code, each still true:

- **A config dir owned by another user runs `claude` as that user.** `harness.command`
  builds `sudo -n -u <owner> -H env -C <dir> <what the caller set> <owner's claude> ...`,
  carrying only what the caller added to the environment and running in the caller's cwd
  when it lies in that user's home, else in the home. Every harness call goes through it,
  a house's included. Bosun never starts that way: when the personal space's config dir
  belongs to another Unix user, its Start is refused in one sentence (`console.other_owner`,
  from `console.refuse_builder`), since its settings and key are written 0600 in this
  user's own directory.
- **Its wake.** A bypass session HOLDS a peer message from a session in another permission
  mode, which the drain's wake is, so Bosun's settings carry `crossSessionInbound: "accept"`
  whenever `[console] permission_mode` is bypass and it is not an install's builder
  (`console.settings`; seen on its first start, 2026-09-29).
- **The git gate** (`keel/gitgate.py`), how it landed. Its ssh key reached Keel's user with a
  forced `bin/keel-git-gate`: `git-upload-pack` or `git-receive-pack` on Keel's repo only, marked
  `KEEL_GIT_GATE=bosun`. The repo's `pre-receive` is `bin/keel-git-receive`: for a gated
  push, `refs/heads/next` only as a fast-forward and never deleted, and `refs/heads/bosun/*`;
  every other ref, `main` above all, is refused. Other pushes pass untouched.
- **`kb tested <commit> [--repo] [--space]`** (`cli.cmd_tested`): the superuser Bosun's (or
  the user's) word that `make test-all` (every module, voice passing) ran green on a commit already in the repo
  where the board lives; `merging.record_tested` keys it by tree, so the deploy of that exact
  tree skips its full suite. A narrow `make test` run is not that word (c-646): the verb is
  refused unless a worktree of that repo recorded a green `make test-all`, voice passing, at
  that exact commit on a clean tree (`keel/review/testrun.py`, `testrun.full_green`), and the
  refusal says to run `make test-all`. A house may not, and neither may an install's builder
  (`authority.refuse_tested`). From the page it is the deck action `tested`
  (`actions.ARGV_BUILDERS`).
- **The user's terminal.** `keel console attach` joins the running Bosun (`claude attach`, the same
  session, `console.attach`), starting it first when it is down.

## The page and the entry

- **The header entry** (`bosunEntry` in `app/ui.core.js`, [the deck](40-deck.md)), left of
  the drain pill: a pill on the desk, a 44px icon on the phone.
- **The Bosun page** (c-591) is `app/console.html`: the deck's core and `app/ui.console.js`
  (with `app/ui.console.asks.js`, the asks and the card links, loaded before it),
  not the deck's boot and not its Inspector. It wears the deck's own shell (`nav.rail`,
  `header`, `main.body`, `nav.dock`, `ui.css`'s classes), so the desk has a left rail and the
  phone a bottom tab bar, and it shows ONE of four sections at a time, each a route of the
  one shell (`serve.CONSOLE_PATHS`, `serve.CONSOLE_SECTIONS`): `/console` (Now, the default),
  `/console/queue`, `/console/shipped` and `/console/journal`. A tap pushes the route, so
  Back walks the sections. A link from before c-591 still lands: `?tab=needs` is Now,
  `requests` and `board` are Queue, `journal` is Journal, and `?card=<id>` goes to the deck's
  Inspector. It registers the deck's shell worker (`app/sw.js`, whose list holds its routes
  and files), so a switch from Keel reuses them, and every file is kept and revalidated
  rather than fetched again (c-540).
- **Its cards are the ones Bosun builds.** It reads `/api/state?scope=bosun`
  (`K.stateScope`; the scope was named `console` until c-593), whose cards are those with
  `derived.bosun` ("Builder mode", above: personal, with a repo, builder mode on); every
  top-level list and count is still the whole board's ([the deck](40-deck.md),
  the deck's state document). Because Bosun's status can change without writing anything on
  the board, it loads again on every stream tick. **A card opens in the deck's Inspector**
  (`/?view=cards&card=<id>&space=<space>`), never on this page.
- **Now**: the session panel (status, model and window, up since, last turn, the context
  meter with the compaction mark, Open in Claude app, Start or Restart, Stop, and the attach
  command with Copy: the state's `console.attach`, this install's own
  `<home>/bin/keel console attach`, run in a terminal here, c-634), the batch in hand
  (Bosun's cards at planning to shipping, grouped by `options.bosun.batch`, each with its
  branch), and **Needs you**: the user's plan gates on Bosun's attended cards, Bosun's open asks
  (each with its kind, its card, "Why:", its options as buttons, A marked recommended, a
  tap asking one confirm, and "Something else" for the user's own words), and held discussions
  (Bosun's blocked cards, the block's first line; a held card Bosun has an open ask about
  shows once, as the ask). The deploy ask is Shipped's, not here.
  The asks answered in the last day fold below, then the Logins panel ([the deck](40-deck.md),
  "The Logins list"); the drain's login asks are among the asks, each with its one-liner and
  a Copy button, answered and never told to Bosun.
- **Queue**: Bosun's cards by state, each a row that opens the Inspector: Waiting on you
  (`needs_you`: a plan gate, an ask, a hold, an outcome gate), Doing (planning to shipping,
  with batch and branch), Will do (inbox and assigned). Beside them the **Intake**: the
  open and taken requests ("Requests", below), each open one with Copy for chat.
- **Shipped**: what is on `next` and not live, the cards the open deploy ask carries
  (`deployask.shipped`, read from the asks and their moves, nothing kept), with **Deploy**,
  which answers that ask with A after one confirm (the `console answer` verb, the user's tap);
  it, the asks and the Journal read the state's board half (`deckstate.bosun_board`), which
  comes without a console session too;
  the last deploy's result (starting, building, testing, going live, deployed, live
  everywhere, not deployed, with its words and time) and each phase it has passed with the
  time it began (`deployask.steps_of`, c-636): the user's tap reads `starting` the instant the
  answer is recorded, and the same `kb` kicks the drain, which starts the worker at once
  (its toast says "the deploy starts now" only when a drain heard the kick, else "waiting
  for the drain"; an answer untaken for two drain polls reads waiting for the drain, unless another Deploy of
  the repo still has a live worker; a
  worker's first phase reads `started`; a deploy of Keel whose deck was not seen on the new
  code reads "deployed, deck not restarted") ([the drain](30-drain.md), "Deploy: the ask,
  and the user's Yes"); and recently live (the cards of the last deploys that landed on main).
- **Journal**: "The Journal", below.
- **The counts**: Now's is its Needs you (plan gates, asks, holds), red; Queue's the open
  requests, grey; Shipped's the cards the open deploy ask carries (at least one), red. The
  page's title carries Now's.
- **What c-591 removed**: the Board tab and its six lanes, the Driven cards and Strikes
  panels, and the console-card Inspector (the drawer on the desk and the route on the phone,
  c-537). c-593 then removed the verbs and the data behind them ("Retired in c-593").
- **Installable on its own**: the manifest (`app/console.webmanifest`, c-518) is scoped to
  `/console`, so a home-screen Bosun opens there, never inside the deck.

## Harbor and Bosun (BO-5)

c-523 built Harbor's side of c-517's design: four tools, and Bosun's words for what happened.
Harbor's memory of it is `<install>/memory/talker/bosun.md`; the per-turn teaching is
`harbormsg.BOSUN_NOTE` in `voice/harbor_voice/harbormsg.py`, which rides with the connect
note because both carry the turn's key.

| Tool | How | What the user hears |
|---|---|---|
| File a request | `kb --actor voice console ask "<a line>" --detail "<the user's words>" [--card c-NNN]`; its payload's `say` line (`requests.spoken_ask`) | "Filed with Bosun as request 23." or "Bosun already has that as request 19." |
| Read its status | the voice digest's `bosun` section (`deckdigest._bosun`: state, open asks with option labels, real counts; never an option's `does`); `keel deck bosun` on the phone | "Bosun has a question for you", its state, the counts |
| Answer an ask | Harbor reads the options, says the user's pick back, and on the user's yes ends with `<<keel-answer a-31 A key>>` (`verbs.answer_directive`: a letter only, this turn's key, the end of the answer, spoken; an answer in the user's own words goes on the Console or in the chat, since only the user's "yes" would be recorded); the gateway hands it to the voice page (`{"type": "answer"}`), and the page posts the Console's answer with `voice: true` | the ask records channel voice, the user's confirming sentence as its words |
| Connect | "put me through to Bosun" (`verbs.target_in`), or `<<keel-connect bosun key>>`; `keel converse bosun` (`keel/bosuntalk.py`) | "Entering Bosun, the admin console." and back to Harbor as for a house |

**The answer is recorded by the page, never by Harbor.** An answer by voice must carry the user's
token (`cli.cmd_console`), and the gateway holds none. The voice page is the user on the deck
(its cookie and origin are the human path's proof, `keel/deckauth.py`), so it is the page
that posts, and `actions.voice_answer` lets `voice: true` through on exactly one body, the
page's own `console answer`, running `kb --actor voice` with the deck's token. Anything else, and
any other verb or sub-verb carrying the flag, is refused. It is the one thing the voice page
posts to `/api/action`.

**Connecting is a house's hold, on Bosun's session.** The mechanism is `keel/converse.py`'s
with nothing copied: `housetier` opens, speaks and closes on this machine's loopback tier with a
pseudo card (`bosuntalk.pseudo`) that names Bosun. What a card would have supplied is Bosun's:

- **The hold** is the one row of the board's `holds` table keyed `bosun`
  (`keel/bosunhold.py`), with a card hold's shape and reading (`views.voice_hold`): `at` set
  once, `stopped` set once, `turns`, `until`. The user's answer at c-523's plan gate put it on the
  board rather than in `state/console.json`, because the board is the one store. Voice, the
  drain and the user may write it (`board.HOLD_ACTORS`); a house and Bosun may not. `kb console
  held` reads it (a read to the deck), `kb console hold` takes, refreshes or `--release`s
  it.
- **The plan** (`bosuntalk.door_plan`) is its cwd (`console.cwd`: Keel's
  root, or on an install the builder's clones, never a live checkout; the wake runs there
  too), personal's config dir, its settings file (which carries its key, c-553), its model
  and permission mode (`console.permission_mode`: auto for the install's builder), and
  its launch environment, so its `kb` is still `bosun` mid-conversation
  (`housetalk.extras_of` hands `env` and `permission_mode` to `harness.open_conversation`).
- **The guards** (`bosuntalk.ready`) add Bosun's own: never started, stopped and stuck are
  refused, so voice only holds a Bosun it stopped itself; mid-turn is refused; and a turn in the transcript under two minutes old that is newer
  than voice's last release (`voice_released_at` in `state/console.json`) is read as the user
  typing to it in the app and refused politely. The open takes the user's tap lock, so a Start
  cannot race it; an open that stopped Bosun and then failed wakes it again. A sentence the
  tier no longer has a conversation for is refused (never silently reopened
  past the guards) and the pin is dropped.
- **The wake** (`bosuntalk.wake`) is `harness.wake` with no flags and no prompt under
  Bosun's own environment (never a `KEEL_CARD`). Probed for this card on 2.1.283
  (`state/cards/c-523/probe/README.md`): stop, one headless turn, then the flagless wake
  kept the session id and the log said remote control was active at the same link. A build
  that answered with a new id would be followed: the record takes it and the next status
  asks the log for the link.
- **The record** is Bosun's own transcript and the Journal: "voice connected", "voice
  released; Bosun is awake again", or the wake's failure when it failed. The deck's
  revision reads the `holds` row, so a hold taken or released repaints at once.

**What ends a hold without "back to Harbor".** The user's Start, Stop or Restart
(`bosuntalk.voice_ended`, the first step of `consoletaps.tap`) closes the conversation with no
wake and clears the hold as voice (the hold is voice's to clear), then the tap acts; a Stop that finds voice had already stopped the
session records that and is done. The drain (`drain.bosun_hold_upkeep`,
before the wakes) closes and clears a hold that ran out and wakes Bosun if voice stopped it,
doing the wake itself when nothing serves the conversation, and writing the Journal when
the close failed or its own wake did. A "back to Harbor" whose close failed runs the hold out at once rather than clearing it, so no turn reads it as live
and that drain repairs it; a connect over a hold that ran out repairs it first the same way,
or says the last conversation is not closed yet. A drain wake while voice holds
Bosun is not sent: Bosun is not idle, so the answers wait for the hook.

**On the page.** The deck's state marks `console.voice` from the board
(`deckstate.console_entry`), so the header dot and the Console strip say "on voice" (`bosunWord`, the
iris accent) the moment it is taken. The voice page wears the
console's iris while pinned to Bosun and reads "Hold to talk to Bosun".

## The Journal

The Journal section (`/console/journal`; c-524, `keel/consolejournal.py`) reads, top to bottom:

- **Done in the last 7 days**: two tiles, Personal and Work, each the cards that reached
  done inside `consolejournal.DAYS`, by a stage move or by a gate (the user's Approve outcome and a
  landing record `approve` events), each card once. (The console space's tile and its
  in-flight count went with c-591 and c-593.)
- **Recurring gaps**: every gap tag a resolved request carries, most requests first, with
  how they ended, when last and which requests; a tag on `consolejournal.RECURRING` (2)
  requests or more carries the warn pill `recurring`, and the rest fold under "Seen once".
- **The feed**: the session's taps (a compaction among them, by `harness`) and the requests'
  and asks' moves, newest first, each request's ending with its gap tag as a pill.

`deckstate.console_entry` carries them as `throughput` (`days`, `done` by space) and `gaps`
(`consolejournal.gap_rows`), read from the board where it lives. `kb console gaps` prints the same rows.
