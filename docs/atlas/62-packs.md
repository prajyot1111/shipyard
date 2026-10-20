# Packs

A pack is an integration as one directory: an adapter on the contract [the work
adapter](60-work-adapter.md) states, plus the rules its houses read, the skills it brings,
the config it adds and the tools it needs on the machine. There is no plugin API beyond
that contract: the engine still runs one executable per verb, JSON in and out, and a pack
only adds a `pack.toml` that says what the directory is (c-617, step 3 of c-610).

Three packs ship in the repo, and an install may hold packs of its own:

- `packs/sandbox/`, the example: the same verbs over a JSON code host and tracker on disk,
  which the demo sandbox runs on. Copy it to start a pack of your own.
- `packs/github/`, the neutral code host (c-689): pull requests on github.com through `gh`,
  GitHub's command line tool, with no tracker and no token. It is a host layer on the pack kit
  (c-735, "The pack kit" below). "The GitHub pack" below.
- `packs/gitea/`, a code host on the pack kit (c-735): pull requests on a Gitea through its
  API, with the sign-in git keeps. "The Gitea pack" below.
- An install's own pack, in its packs repo (`<install>/packs/<name>/`): one owner's work pack
  (the tracker's stories, the code host's pull requests, the worktree and preview verbs, and
  the stack's rules) left the repo for its install (c-722 landing B). It is the one place
  outside `docs/` that may name the employer. Its suite runs in the adapters job whenever
  `KEEL_CONFIG` names that install (`tests/packsuites.py`, c-726 r1.F4), at a landing the
  job reaches and at every deploy; its terms are checked by `tests/installdrift.py`.

## The layout

```
packs/<name>/
  pack.toml             what the pack is, provides and needs (below)
  <verb> ...            the adapter's executables at the root: worktree, brief, pr, publish,
                        publishable, deny, ship, review, act, logins (the ones it answers)
  guard                 reads each command its houses run, when it has a [guard] (optional)
  ready                 its own requirement checker, when its checks are more than a
                        shell test (the GitHub pack's; optional, and no engine verb)
  *.py                  the modules behind them
  options.json          the card options the deck offers for its space
  providers/<route>     extra deck routes (optional)
  rules/*.md            the markdown its brief reads, and onboarding can import
  skills/               skills it brings (optional)
  pipeline.md           its words for the pipeline's Verify, Preship and Publish (optional)
  config.example.toml   a space on this pack, as the install's config writes it
  setup/*.md            the text of its own first-run steps, [[setup]] (optional)
  drift-terms           words only this pack may say (optional)
  tests/                its own suite (optional)
```

### A pack's guard

A permission deny entry matches a command's text. That is enough to take a whole tool away,
and not enough to tell `gh pr view --json mergeable` from `gh pr merge`, or a commit
message from a command. So a pack may ship a **`guard` verb** (c-689) and read the command
itself. It says so in `pack.toml`:

```toml
[guard]
tools = ["gh"]      # the command words the guard reads
```

`packs.load` refuses a `[guard]` with no executable `guard` beside it, and a pack that
shows a guard (the file, or `[guard]` in its `pack.toml`) and does not load BLOCKS the card
at launch (`house.pack_guard` raises, as a failing `deny` verb does), so a house is never
started without the guard its pack says it has; a pack with no sign of a guard and a fault
of its own starts as it did. For a card whose
space is on such a pack, `house.pack_guard` puts the verb's path and the tools on the house
guard's hook command (`keel-house-guard <card> <pack>/guard gh`), and on every Bash call
`bin/keel-house-guard` runs `<pack>/guard <card>` with `{"command", "cwd"}` as JSON on stdin,
as every verb is run (`KEEL_HOME` set, `kb` on PATH). The pack prints `{"allow": true}`, or
`{"allow": false, "why": "<one sentence>"}`, and that sentence is the refusal the house
reads (an `allow: false` with no sentence is still a refusal, with the hook's own words).

**The order** in the hook: first the `pgrep -f` loop, then the pack's guard, then the hook's
two push checks (a push at shipping, a push to a shared branch), which hold whatever the
pack allowed. So a push the pack refuses is answered with the pack's sentence at any stage,
and one it allows still meets the board.

**One clock.** The harness stops the hook at twenty seconds, and a hook it stops refuses
nothing. So the hook takes one deadline, 17 seconds from its start (`BUDGET_SECONDS`): the
pack's guard gets four of them at most (`PACK_SECONDS`), `keel/flowfence.py`'s git reads and
`kb flowinfo` share what is left, and a push check the budget cannot finish reads as unread,
which is refused. Run by hand with no deadline, each part keeps its own clock.

- **A pack with no `guard` verb is named nowhere**: its houses' hook command and the hook's
  behaviour are what they were, byte for byte (`tests/test_house.py`,
  `tests/test_house_guard.py`). The work pack and the sandbox pack have none.
- **A guard that fails** (it errors, answers something that is not that JSON, is missing, or
  gives no answer in four seconds) refuses a command that names one of the pack's `tools`
  as a word, since that is what it is there to read, and allows every other command, so a
  broken pack never takes a house's shell away. One that gave no answer in time says to try
  again; one that is missing or broken names itself and says waiting will not mend it.
- The guard runs on every Bash call, so it must be fast and must not ask the board or the
  network for a command it can judge from the line.

The executables sit at the root, as they did under `adapters/<name>/`, so the move to
`packs/` changed no verb, no path depth and no output.

## pack.toml

`keel/packs.py` reads and validates it (`packs.load`); a broken one is refused with the
key it is about, and `keel doctor` names it as a problem.

| Key | What it says |
|---|---|
| `name`, `version`, `description` | strings; `name` is the directory's name |
| `demo_only` | true or false (c-688): the pack runs only in a demo, so Setup does not offer it on an install. See "Demo-only packs" below |
| `[adapter] spaces` | the space kinds its adapter serves (`work`) |
| `[provides] rules` | files under `rules/`, each must exist |
| `[provides] skills` | paths under `skills/`, each must exist |
| `[provides] pipeline` | the space's `pipeline` when the space names none |
| `[provides] config_example` | the example space table |
| `[space]` | defaults under a `[spaces.<name>]` that names this pack; the space's own keys win. Never `allow`: what a house runs unasked is the space's own table's to say, so a pack's `[space]` that names it is a warning at load and is not read (`config.space_allow`, [houses](20-houses.md)) |
| `[[requires]]` | a tool the pack needs: `name`, `kind` (command, repo-command, skill, hook or secret), `check` (a shell test, exit 0 is found), `why`, and optionally `for`, the capabilities it serves (each one `[capabilities]` declares), and its own fix: `fix`, `command`, `done_when` and `action` (c-688). See "A requirement's own fix" below |
| `[terms]` | what the pack calls things (c-630): `ticket`, `tickets`, `ticket_ref`, `change`, `changes`, `change_short`, `changes_short`, `tracker_name`, `codehost_name`, each a string as it reads mid-sentence (`"story"`, `"the tracker"`). `ticket_ref` is a ticket's shape as `options.json`'s `normalise` writes it, a prefix of letters, digits, `-` and `_` and one `<n>` (`sc-<n>`), never a raw regex. An unknown key, a non-string or a bad `ticket_ref` refuses the pack (`packs.terms_of`). See "Terms" below |
| `[[setup]]` | its own first-run steps (c-632): `id`, `title`, `text` (a markdown file in the pack), and optionally `after` (a core step), `for` and `requires`. See "`[[setup]]`" below |
| `[capabilities]` | what the pack provides (c-629): `tracker`, `codehost`, `reviews`, `ci` (true or false) and `routes`, the `providers/<route>` executables it ships. Each claim needs its executables at the pack's root, or the pack is refused naming the missing ones (`packs.NEEDS`): `tracker` needs `act`; `codehost` needs `publish`, `publishable` and `ship`; `reviews` needs `review` and `providers/reviews`; `ci` needs `ci` ([a card's CI](66-ci.md), c-642). `flow_pr` (c-664) is one more claim, of a different kind: it says the pack's `pr` takes `--flow <branch> --to <target> --dir <worktree>`, the change a flow move's `opens` asks for ([flows](64-flows.md)); it needs `pr`, and a flow with `opens` is refused for a space whose pack does not declare it (`keel flow check --space`, Adopt). A pack declares it by writing `flow_pr = true` under `[capabilities]` once its `pr` has that form, as the work pack does; the sandbox's `pr` has none, so it does not. It is not a readiness row: nothing on the deck shows it. `stacks` (c-718) is a claim of the same kind: its `worktree` cuts a card stacked on the card it waits for from that card's branch, its change aims there while that card has not landed, and its `ship <id> restack` aims it at the base once it has; it needs `worktree` and `ship`, and `options.stack` is refused in a space whose pack does not declare it (`Config.stacking`, [cards and gates](10-cards-and-gates.md), "Stacked or independent"). The work pack declares it. `review_reap` (c-734) is one more: its `ship <id> reap` for a REVIEW card removes only the paths it recorded when it cut that card's trees (`options.worktree`, `worktrees`, `review_worktrees`), with its own teardown, never a tree found by branch; it needs `ship`. Keel reaps a done review card's tree with plain git only where its own layout cut it (`spaces/<space>/<key>/trees/`), and a tree a pack keeps anywhere else is reaped only through a pack that declares this; without it the tree is left alone (`keel/reviewreap.py`, [the drain](30-drain.md)). Its answer is `{"removed": [<path>], "kept": [{"path", "why"}]}`, and it may add `"later": true` (c-743) when it keeps a tree for a reason that will pass (a session live in it, sessions it cannot list, another card still using it): Keel then leaves the round unmarked, says why on the card once, and asks again on a later pass, as it does when the command fails or times out. Without `later` the round is marked cleaned up whatever was kept, as before. A pack may declare `review_reap`, and an install's own pack can; the kit's packs cut inside Keel's layout and do not need it |

Any other top-level key is refused, so a typo is not a setting nobody reads.

**A requirement's own fix** (c-688). A `[[requires]]` entry may say what to do when its check
fails, and whoever draws the failing check draws that:

```toml
[[requires]]
name = "git"
kind = "command"
check = "command -v git"
why = "the worktrees are git worktrees of bare origins on this disk"
fix = "Install git. On macOS the command line tools bring it."   # the sentence
command = "xcode-select --install"                               # one line the user copies
done_when = "`git --version` prints a version."                  # how the user knows it worked
action = "..."                                                   # optional: a shell line a button may run
```

Each is one line of text, and `command`, `done_when` and `action` each need a `fix` to stand
under: `packs.load` refuses an empty one, one that is not a string, one with a line break, and
one of the three with no `fix` (`packs.fix_of`). Any other key of an entry is ignored, as it
always was. `packs.checks` returns the four on the check, and only the ones the pack wrote, so
a check with no fix reads exactly as before. Until c-688 the loader dropped them, so no page
could show a pack's fix.

**These four keys are checked now, where they were ignored before.** A pack written before
c-688 that already says one of them in a way the rule refuses (a `fix` over several lines, a
`command` with no `fix`) no longer loads. The refusal is one line that says the pack, the
entry and the key: `forge/pack.toml: the forge pack's [[requires]] 'gh': fix must be one line
of text`. Where it shows: a space that names the pack fails the config load with that line
(`config.adapter_of`), which is what `keel doctor`, the deck and the drain print when they
start; a pack no space names empties Setup's pack list, and the Packs panel shows the line in
place of the list (`packsetup.rows` answers `([], error)`, and the page does not also say "no
packs found"). Load every pack of an install's own `packs/` (`keel doctor`) before deploying
this change over one.

Who draws the four:

- **Setup's pack rows and a pack's own first-run step**: the failing check is the stuck line
  ([onboarding](89-onboarding.md), "A requirement that needs you"), and its fix part is the
  sentence, the command with Copy and the `done_when` sentence (`K.fixOf`, `app/ui.stuck.js`).
- **Readiness**: a capability row that a failing check holds up carries those checks as
  `needs` (below), so the first run's Where finished work goes step draws the same fix on the
  row.
- **`keel doctor`**: under the pack's line, for each missing tool that says a fix, the
  sentence, then `run:` with the command and `then:` with `done_when` (`doctorpacks.fix_lines`, `keel/doctorpacks.py`: the pack lines of `keel doctor`).

`action` is loaded, validated and returned, and nothing runs it yet: no verb takes a pack's
line and runs it from the page, so the deck draws no button for it. The pack that first needs
one brings that verb with it.

**Demo-only packs** (c-688). `demo_only = true` says the pack cannot do real work: the sandbox
says it, since its verbs refuse outside a demo sandbox (`sb_card.home`). On an install (a
config that is an install's `config.toml`, `setupconfig.installed`) `packsetup.rows` leaves
such a pack out of the list Setup and the first run offer, unless a space there is already on
it, in which case it is listed so it can be turned off. Where the config is not an install's
(the demo sandbox's own `keel.toml`, the checkout's) it is listed as any pack. It is a rule
about what is offered, not a refusal: `packsetup.pack_on` named outright still turns it on,
which is how the suite and a scratch install use the sandbox. `keel new pack` leaves the line
out of the copy it makes, so a new pack is offered ([Extending Shipyard](63-extending.md)).

**`[[setup]]`: a pack's own first-run steps** (c-632). A pack may bring screens to the deck's
first run ([onboarding](89-onboarding.md), "The first run"), one entry each:

```toml
[[setup]]
id = "tokens"                       # a name, unique in the pack; the stepper's id is <pack>:<id>
title = "Connect the tracker and code host"
text = "setup/tokens.md"            # markdown in the pack, which must exist
after = "integrations"              # a core step id (packs.SETUP_AFTER); integrations by default.
                                    # `spaces`, a step until c-677, is read as `repos` (packs.SETUP_MOVED)
for = ["tracker", "codehost"]       # optional: capabilities it sets up, declared in [capabilities]
requires = ["tracker token"]        # optional: names of this pack's [[requires]] entries
```

`packs.load` refuses an unknown key, a missing text file, a `for` the pack does not declare,
an `after` that is not a step, a `requires` no `[[requires]]` names, and an id used twice,
each by name. A step is never required. It is done when every check it `requires` passes and
every capability it is `for` is ready, in each space on the pack, and it appears after its
`after` step for as long as a space is on the pack. The work pack's one step explains its two
tokens; the sandbox's, "Try the sandbox", needs only `git` and is there so a pack step runs on
a scratch install.

**Capabilities are declared, never guessed.** A pack with no `[capabilities]` provides none of
them, whatever verbs it ships: the deck asks `readiness` (below), and readiness asks the
declaration. Review scanning is the one a space may also say no to (c-730): with
`[spaces.<name>] review_scan = false` it is not declared for that space ("review scanning is off
for <space>"), whatever its pack can do, and a pack's `[space]` may start it off for every space
on it, as the GitHub pack does. Like `ci`, it is optional for the first run: a space that has
not asked for it is set up without it (`readiness.OPTIONAL`). So is the tracker (c-730): a
code host alone, as the GitHub pack is, finishes Where finished work goes. A capability is READY in a space when the space's pack declares it and every
`[[requires]]` whose `for` names it passes its check. `adapters.routes_of` gives the provider
routes the deck and the push read: the pack's declared `routes`, or `("reviews",)` for an
older `adapter =` directory with no `pack.toml`.

## Readiness

`keel/readiness.py` answers "is X set up here, and if not, why, and which first-run step fixes
it", and `/api/state` carries the answer as `readiness` ([the deck](40-deck.md)):

```
{"install": {"prerequisites", "login", "voice", "builder", "segments", "phone", "browser", "backup"},
 "spaces":  {"<space>": {"repos", "tracker", "codehost", "reviews", "rules"}}}
```

Each row is `{ready, why, step}`, `declared` on a capability row (c-730: the space may use it
at all, so a row held up only by a failing check is declared and an undeclared one is not; the
deck draws a page that needs it only while some space declares it), and `needs` on a capability row that a failing check holds
up: those checks as `packs.checks` returned them, each with its own fix where the pack wrote
one (c-688). `why` is one sentence a person reads, `step` the first-run
step id (`repos`, `rules`, `integrations`, `prerequisites`, `login`, `builder`, `browser`,
`backup`, and `set-up`, the last screen, for `phone`; None for segments and for `voice`, which
no step sets up, so its needs panel sends the user to Bosun instead, c-729). `repos` is ready when the space lists a repo whose path holds `.git`, the
install's own `packs` repo not counted. `voice` is ready only while it answers. Three rows
came with the first run (c-632, [onboarding](89-onboarding.md)):

- `login`: the install's Claude login as `keel/login.py` last recorded it for personal,
  never probed here. `good` is ready; not checked yet and `expired` are not: "Shipyard is not
  signed in to Claude yet", or "Shipyard's Claude sign-in ran out, so no session can run" for a
  dir that held a sign-in once. Neither names a command (c-678): the step the row points
  at shows the one. `unknown` (a timeout, a network failure) is ready with that said, since a
  login that could not be checked is not a missing one.
- `phone`: `tailscale serve status --json` (5 s timeout, `TAILSCALE_SECONDS`) has a handler
  that proxies to the deck's `serve_port`, and the row names the address. It is read on an
  install only, and only read: Keel never runs `tailscale serve`.
- `browser` (c-678): Keel's own browser is in its folder (`browserinstall.presence`: the
  package and a Chromium build under `browser.home()`). Presence only: nothing is launched
  to answer it. The A browser for sessions step installs it ([onboarding](89-onboarding.md)).
- `backup` (c-678): the config names a backup store (`[backup] store`). Whether the
  copies are fresh is the tool's own alarm ([backup](85-backup.md)), not this row.
- `rules`: the space tier `<install>/spaces/<space>/CLAUDE.md` exists and is not the
  template text it starts from.

The slow readings (a pack's checks, `prereqs.gather`, `tailscale serve status`) are kept
for five minutes per process (`KEEP_SECONDS`), a failure included, and a reading that fails
is a row that says so, never an error the deck sees. `readiness.forget()` drops them: the
Setup report and the first run's Check again call it, so the next state reads afresh. A
loaded pack is kept too (`packs.load`, c-628 review), since one state build asks a space's
pack a dozen times: it is read again when `pack.toml` changes, or a file is added, removed or
renamed in the pack's directory or its `rules/`, `skills/`, `setup/` or `providers/`, or a
verb there changes mode (`packs.stamp`), and `readiness.forget()` drops it as well.

**The backend refuses with the same sentence** (c-631). `readiness.refusal(cfg, space, cap)`
is the reason a verb that needs `cap` may not run, or None: for `repos` the repos row's `why`,
and for a capability the sentence `readiness.undeclared(space, cap)` gives when the space does
not declare it (no pack, a pack that does not load, a pack without it), which is also the
row's `why`. It refuses on the DECLARATION only, never on a failing check (decision
`refusal-basis`): a check's answer is cached for five minutes and may be stale, and a verb
whose check fails runs and fails in its own words. An older `adapter =` directory with no
`pack.toml` is never refused, as `routes_of` still serves it. Who asks it:

- `adapters.publish` (Approve outcome, and Ship through `kb ship`): a
  repo card in a space whose pack does not declare `codehost` is refused before the pack runs,
  and a card with no repo there has nothing to publish (decision `publish-without-codehost`).
  A space with no pack is never refused: its `publisher` merges locally, as it always has.
  `deckstate.publish_refusal` says the same at the outcome gate, as c-551's `unpublished`.
- `actions.act_adapter`: the `reviews` route (Scan now, the fetcher's settings) needs
  `reviews`, and the `card` route (a card's own verbs) needs `tracker` (`ROUTE_NEEDS`).
- `reviewcards.upkeep` skips a space that does not declare `reviews`.
- `kb create` and `kb set` with a repo (`cli.refuse_unknown_repo`): a space served here that
  lists no repo and has no `projects_dir` refuses any repo with the repos sentence, and an
  unknown repo's refusal leads with it while no repo is cloned. A space served on another
  machine keeps the pass, since this config cannot see its repos.

## Terms

The words a user reads for a ticket and a change come from the space's pack (c-630).
`keel/terms.py` holds the core's neutral defaults (ticket, pull request, PR, the tracker,
the code host, and no `ticket_ref`, so nothing is linked) and lays the pack's `[terms]` over
them:

- `terms.of(cfg, space)` is a space's words, a `Terms` mapping. A space with no pack, an
  older `adapter =` directory with no `pack.toml`, or a pack that does not load reads the
  defaults (readiness reports the failure).
- `terms.say(t, template)` fills `{key}`, and `{Key}` capitalises the first letter; a field
  that is not a term is left as written, so a template can still be `.format`ted. In an
  f-string, `t["change"]` reads the same.
- `terms.public(t)` is what the deck reads: `/api/state`'s space entry carries it as `terms`,
  and the plan payload's `card` carries its space's (`keel/planroute.py`), which `K.term` and
  `K.say` read ([the deck](40-deck.md)).
- `terms.refs(t)` is the plan page's reference pattern for a card's space: cards and paths
  always, the ticket ref from `ticket_ref` (`sc-<n>` is `sc-\d+`), and the change ref as
  `<change_short> #<n>`. `planformat.parse(text, name, refs)` hands it to every span
  (`planinline.using`); a caller with no card (the plan installer, the lint's file facts)
  links only cards and paths. The plan page (`planroute.payload`) and the gate's answers
  (`planactions.document`) pass the card's own.
- The backend's notes, refusals and house briefs fill templates from their card's space:
  the shipping and review notes, the review brief and the reviewer's prompt, the shipping
  round. `Board` takes `terms=` from `local_board` (a space's name to its `Terms`), so its
  refusals say the space's word; a `Board` built without it, as in tests, says the defaults.
  CLI help, which has no space, says the defaults. Readiness names a ready tracker or code
  host by `tracker_name` or `codehost_name` where the pack declares one.

The work pack declares story, `sc-<n>`, pull request, PR and its two vendors' names. The
sandbox declares issue, `st-<n>`, merge request and MR: every word differs from both the
defaults and the work pack, so a sandbox card shows at once that the words came from its
pack, and a pack for a merge-request code host can copy the table.

**The noun guard.** `make drift` runs `python3 -m tests.nouns`: it reads every string literal
of `app/*.js` and `keel/**/*.py` (comments, docstrings and regex literals skipped, an
f-string's and a template literal's text parts read) and fails on story, stories, pull
request(s), merge request(s), PR(s), MR(s) as a word, or `sc-` and a digit. A literal that is
a bare lower-case identifier (`'story'`, `options.pr`, `tracker_ref`) is a data key and never
flagged, so data keys keep their names. `tests/nouns-allow` lists the exceptions as
`path | literal | why` (`keel/terms.py` whole, and the plan format's `PR body` section name),
and an entry that matches nothing fails too.

## How a space names a pack

```toml
[spaces.work]
pack = "work"
config_dir = "~/.claude"
```

`config._space` (through `adapter_of`) resolves it: the space's `adapter` is the pack's name,
its adapter directory is the pack's directory, the pack's `[space]` table is laid under the
space's own keys (all but `allow`, which is read from the space's own table only), and its
`pipeline` is used when the space names none. A space may name `pack` or `adapter`, never both.

Packs are looked for under the install's own `packs/` first (`<dir>/packs/`, the directory
of the `config.toml` that `KEEL_CONFIG` names, `packs.install_packs`), then the code's
`packs/` (`packs.roots`), the first of a name winning (c-618). `packs.find` refuses a name that is not
a plain identifier (lower case letters, digits, `-` and `_`). An install adds an
integration by putting a pack in its own `packs/`, never by editing the checkout. A pack
the checkout also carries is read from the install once the install has it, which is how an
owner's own pack leaves the tree: `shipyard move-personal` copies it into the install
([install](88-install.md), "Moving your own things into the install"), and from then on the
checkout's copy is not read. Segments follow the same rule (`Config.segment_roots`), and
`tests/test_install_first.py` holds both, with scratch names, for a pack and five segments.

## The install's packs repo, and how a pack lands

`<install>/packs` is a git repo on `main` (`shipyard init` makes it, [install](88-install.md)),
listed as the personal repo `packs`, and it is the first repo the builder builds (with any
personal repo `[builder] repos` adds, each from its own clone, landing on its integration
branch where it has one): Bosun builds
a pack on a card there, in its own clone (`<install>/builder/packs`), on a branch
`bosun/c-<N>-<slug>`, and stages review with that branch. The user's Approve outcome lands it:
packs has no integration branch, so landing is live. The landing fetches the branch from the
clone into `refs/builder/<branch>` of the repo (`merging.fetch_built`, never a branch of it) and merges it as any
personal card's branch merges ([cards and gates](10-cards-and-gates.md)). The drain re-execs
when the repo's head moves (or a cloned pack's, "A pack someone shared" below), and the deck and drain read the new pack on their next start
([Bosun](96-bosun.md), "The builder"). "Import my Claude setup" is such a card: the user's
own Claude as the pack `mine` ([onboarding](89-onboarding.md)).

## A pack someone shared

A team keeps its pack in a repo of its own, and a colleague plugs it into an install with
one line (c-740, `keel/packclones.py`). The pack is **its own clone inside the install's
packs folder**, `<install>/packs/<name>/` with its own `.git`:

```
git clone <its address> <install>/packs/<name>
```

The Setup page's Packs panel says that line on an install, with the install's real folder
filled in and the address and the name left as written, Copy on it, and a **Look again**
button beside it; the first run's Where finished work goes draws the very same row under
its choice "Add a connection someone shared with you" (c-758, `K.setupParts.sharedPack`,
[onboarding](89-onboarding.md)), where a connection found in the folder is listed first,
marked "Found in <its folder>" (`folder` on its row, `packsetup.install_folder`: the pack's
path when it lies in the install's packs folder, None for one that ships). Shipyard does
not run the command and never handles a repo's address or credentials. Each page keeps
one word (r1.F7): the Setup view says pack, in this row and in the problem lines
(`packs_error`), and the first run says connection (`opts.noun`, and `connections_error`,
the same lines from `packsetup.listing`). The report also says whether a problem line is
about a folder of the install's own packs folder (`packs_error_install`, r1.F13). Nothing in Keel
names any pack's address. The folder comes in the report quoted as a shell reads it
(`packs_folder`, `packsetup.packs_folder`, r1.F8), since the line is there to be copied.

- **Found as any pack there.** The roots do not change: `packs.available` lists the folder,
  and a clone is a folder. There is no second packs folder, and a clone is a real directory
  with a real `.git` directory (`packclones.found`): a link is never read as one.
- **The packs repo ignores it.** `packclones.ensure_ignored` writes a marked block into the
  packs repo's own `info/exclude`, one anchored line per clone (`/<name>/`), with the writer
  the build output block uses (`buildout.put_block`); every other line of the file is kept,
  and the block follows the clones as they come and go. So the packs repo's status stays
  clean, and nothing of a shared pack is ever added to it. It is reconciled wherever Keel
  looks at the packs folder: the Setup report (`onboarding.report`, so Look again writes it),
  the drain's start, and `shipyard init`, which writes it before the packs repo's first add
  and commit where a clone was there before the repo was (r1.F7, `installer.packs_repo`).
- **A packs landing never writes into it** (r1.F2). The ignore line takes away git's own
  refusal: git writes over an ignored file on a merge without asking, and Bosun's clone of
  the packs repo holds neither the folder nor the ignore, so a card on `packs` could commit
  `<name>/...` there. So the landing refuses it: a landing into the install's packs repo
  whose merged tree changes any path under a folder with a repo of its own is a
  `MergeRefused` that names `pack-<name>` as the repo to use (`merging.refuse_cloned_pack`,
  asked right before the fast-forward). And every landing's fast-forward, in any repo, runs
  with `--no-overwrite-ignore` (`merging.settle`): an ignored file in a checkout is the
  user's, and a merge that would write over it is refused with nothing moved. That refusal
  is said in plain words (r2.F2, `merging.refuse_ignored`): which ignored files in which
  checkout the change would write over, that nothing was merged, and to move or delete them
  there and approve again. A landing on the checkout's own branch says it, and the cloned
  pack refusal before it, before the suite is run; `settle` asks again on the merged tree.
  The early asking reads the tree the merge would write (`merging.merged_tree`,
  `git merge-tree --write-tree`, which touches no checkout, index or ref), never the
  branch's tip (r2.D1): a branch behind its target differs from it in every path the target
  changed since, so a file the target untracked and ignored, or a pack that left the packs
  repo after the branch was cut, would read as the branch's own change. Where that tree
  cannot be known yet (a conflict, an old git), nothing is asked early.
- **Its update takes effect without a hand restart.** The drain's restart check reads each
  clone's head beside the packs repo's (`drain.packs_head`, a head per folder), so a
  `git pull` in the pack restarts the drain between passes as a landing in the packs repo
  does. A clone that came with a head, or one that had a head and is gone, moves it too. A
  clone with no head yet (seen mid-clone) is not counted until it has one, and its first
  head restarts the drain once (r1.F6): counted with none, its later pulls could never move
  the check. A head git cannot say now is unknown, and unknown is not moved.
- **The wrong folder name is one problem line.** `git clone` with no folder names it after
  the repo, which is rarely the pack's name. `packs.read` raises `Misnamed` for a folder that
  is not called what its pack is, `packs.available` sets it aside when handed a list, and
  `packsetup.rows` says it as one line, what the folder is and what it should be called
  (`packsetup.wrong_folder`), while every other pack still lists. A name that is no pack
  name is whatever the file says, so it is never shown: that folder's line says what a pack
  name is, and no problem line carries a line break (`packsetup.one_line`, r1.F8). Any other pack that does
  not load still empties the list, and `packs.find` still refuses a misnamed folder.
- **Bosun builds it in its own repo.** A clone that holds a pack under a pack's name is one
  of the install's own repos, under the key `pack-<name>` (`packclones.own`,
  `builder.own_repos`). The page finishes the job by one tap (r1.F1): after Look again, the
  pack's row says "It has a repo of its own. Bosun does not build it yet." with **Let Bosun
  build this pack** (`setup.pack.build` `{pack}`, `packsetup.build_pack`), which lists it as
  a personal repo and names it in `[builder] repos` through the path init uses
  (`builder.list_own`), and makes Bosun's clone, `<install>/builder/pack-<name>`, there and
  then (`builder.ensure_clones`, as Bosun's Start does). It is a tap and not part of the
  report because the report is a read: every config write on Setup is a verb of the page,
  after which the deck re-execs (`onboarding.CONFIG_VERBS`). The row then says the repo's
  key (`own_repo` on the pack's row: `{key, built}`). The tap is offered only where the
  install's builder is Bosun, and the verb refuses anywhere else (r2.F3). `shipyard init <install>`, run again, does the same listing
  for every such clone, adding it to `[builder] repos` when that listing is new. A card on that repo lands as any builder card does (the
  section above), in the pack's repo, as a local merge that is not pushed: the push to the
  team's repo is the user's own, from the pack's folder. Nothing lands in the packs repo.
  `builder.is_own` counts it as the install's, so Setup and readiness do not take it for one
  of the user's repos. A user's repo that already has that key keeps it. Only a clone that
  holds the pack its folder is named for is listed (r1.F5, `packclones.pack_name`): one under
  another name is renamed first. And a listing whose clone is gone (renamed, removed, its
  `.git` gone) is taken out where listings are made (`builder.unlist_gone`,
  `packclones.gone`: a `pack-*` key whose path is inside the packs folder and is no repo of
  its own now), from `[spaces.personal.repos]` and from `[builder] repos`, so it never reads
  as one of the user's repos. `[builder] repos` is written once, from the config text as it
  is (`builder.built_in`, r2.F1), and loses every `pack-*` name no personal repo is listed
  under: two clones gone at once both go, the tap never writes an old key back, and Bosun
  is never left told to build a repo with no checkout to clone. Bosun's clone of it stays on disk: nothing is deleted.
- **Its suite and its terms are read as a tracked pack's.** `tests/packsuites.py`,
  `tests/installdrift.py` and `tests/publiccheck.py` list `<install>/packs/*` on disk, so a
  cloned pack's `tests/` runs and its `drift-terms` hold the tree exactly as before
  (`tests/test_packclones.py` holds all three).

**A folder the packs repo still tracks is not a clone** (r1.F3), whatever `.git` it has: an
ignore line does nothing for a tracked path, and two repos could each land its files.
`packclones.found` asks the packs repo's index (`tracked_under`) and leaves such a folder
out, so it gets no ignore line and is no repo of its own, and the Packs panel says it in one
problem line with the command that stops it (`packsetup.still_tracked`):
`git -C <install>/packs rm -r --cached <name>`, committed there, then Look again. One
report asks the packs repo what it tracks once (`packsetup.tracked_names`) and says the
line in each page's word from that one reading. Where git
cannot say what the packs repo tracks, no folder is a clone. `packclones.nested` is every
folder with a repo of its own, tracked or not: the restart check and the landing guard read
those. Folder names are compared case-folded in both (r2.F4), on every disk: where the disk
folds case, a path under `Team/` is written into the clone `team`, and the index's `Mine/`
is the folder `mine`. A path that is exactly the folder's name counts as well (r2.D3): that
is how git holds an embedded repo, one entry and no path under it.

## Turning a pack on and off from the deck

The deck's Setup view lists every pack the roots hold, each with its description and its
`[[requires]]` checks run on this machine, its `rules` (the first run lists them as already
read by its houses; nothing is copied, decision `pack-rules`), and a Turn on button that asks
for a space's name ([onboarding](89-onboarding.md)); the first run's Where finished work goes step turns
it on for the space picked there. `packsetup.pack_on` takes either:

- **a new name**: it adds the one space the pack's `config.example.toml` shows, under that
  name, to the install's `config.toml`: `pack` set to the pack, `config_dir` set to the
  install's own `<dir>/claude`, and the example's `host` and `repos` left out, so the space
  is served on this machine and its repos are cloned one at a time after;
- **a space that exists and names no pack** (c-632, decision `space-pack`:
  `packsetup.adopt_space`): `pack` is set in its table, and the example's keys are merged in
  only where the space has none (never `host`, `repos` or `config_dir`), so a space added
  plain on the first run's Add your repos step can get its integration after. A space that already
  names a pack or an adapter is refused.

**Turn off** (c-688). A pack's row has one Turn off button per space it is on, and
`setup.pack.off` `{space}` runs `packsetup.pack_off`, which takes back what Turn on wrote:

- the space's `pack` line;
- each key the pack's own `config.example.toml` gives (read at Turn off, as `adopt_space`
  reads it at Turn on: `packsetup.brought`) whose value in the space's table still equals the
  example's, so the sandbox's `contract` and `pipeline` go with the sandbox and the next pack
  turned on brings its own;
- the note "Turned on ...: the <name> pack" that `pack_space` wrote, when it is the line
  directly over the table (`packsetup.without_note`). Any other comment stays.

The space, its repos, its `config_dir`, its `host` and every key whose value differs from the
example's stay; its capability rows read "no connection is turned on" again. The config does
not record who wrote a key, so the rule has two limits: a value the user typed that happens to
equal the example's goes too, and an example edited since Turn on leaves its old keys behind
(as does a pack whose example no longer reads: then only the `pack` line comes off). A key
that was rewritten by hand so that it is no longer one plain line (a list over several lines,
a quoted key) is left where it is, and the answer names it ("left in place: deny",
`packsetup.taken`); that never refuses Turn off.

It is refused:

- **while the space has open cards** (not done, not archived), naming them, as Remove refuses
  a repo an open card names: with the pack off, a repo card at review there would land as a
  local merge where the pack would have opened its change for review, and the card's pack
  verbs would stop. Finish or archive them first;
- for a space on no pack;
- for a space that names an older `adapter =`, or whose table is written inline, by hand: it
  is taken off where it was written.

The page asks first, saying what stays and what comes off. For the last space on a demo-only
pack on an install it says the pack will no longer be listed here, since its row leaves the
list once no space is on it; for any other pack, and while another space is still on that
one, that Turn on puts it back (the row carries `demo_only`). Like Turn
on it changes the config, so the deck re-execs after it (`onboarding.CONFIG_VERBS`).

A config that is not an install's is never written.

**The older form keeps working unchanged.** `adapter = "<name>"` is
`adapters_dir/<name>` exactly as before, missing or not (a missing one is a space with no
verbs, as it always was). `adapters/sandbox` is a tracked link into `packs/`, so a config
that says `adapter = "sandbox"` still resolves to the same files. The work pack's old
link under `adapters/` left the code with the pack (c-722): a space whose `pipeline` still
names the pipeline through that link is pointed at the install's copy by `shipyard
move-personal`. The deny lists (the work pack's `fence.py`, `packs/sandbox/sb_brief.py`) and
`bin/keel-house-guard` refuse a publishing verb by either path.

## Rules

`rules/*.md` is plain markdown the pack's `brief` reads where the brief has always been
composed: `briefing.rule` in the work pack, `sb_brief.rule` in the example. A line that is
exactly `@<file>.md` is replaced by that file's text, so the shared stack warning is
written once (`<install>/packs/work/rules/shared-stack.md`) and taken by each house text. A rule
file a brief formats may use `{placeholders}`; a literal brace is then written `{{`.

The core brief (`etc/house-contract.md`, the space contracts, `keel/review/brief.py`)
carries only generic text. Anything about a stack, its tools, its containers or its
conventions is a pack's rule.

## What a pack declares and does not carry

`[[requires]]` names what the pack uses on the machine its space runs on, and the check
that says it is there. `keel doctor` runs each check for a space this machine serves, in
the pack's directory, with `KEEL_HOME` (this Keel, which a pack on the kit imports it
through), `KEEL_SPACE_CONFIG_DIR` (the space's config dir),
`KEEL_SPACE_REPOS` (the space's repo paths joined by the path separator, `:` on macOS and
Linux) and `KEEL_STACK_GUARD_HOOK` (`[machine] stack_guard_hook`) set, and prints one line: how many
were found and which are missing, and under it each missing tool's own fix where the pack
wrote one (c-688). A missing tool is shown, never a problem: the verb that
needs it says so when it runs. A `repo-command` is a Claude command one of the space's
repos carries under `.claude/commands/`, so its check loops over `KEEL_SPACE_REPOS`.

The work pack declares, and does not copy, the user's own tooling on this machine: the
worktree tools (`wt-repo`, the create and test commands, `wt-preview`, `wt-preview-web`,
`wt-shot`, `wt-budget`), `docker`, the stack guard hook (`[machine] stack_guard_hook`), the
`no-mistakes` skill in the work space's config dir, the `ship-story` command one of its
repos carries (`.claude/commands/ship-story.md`, a `repo-command`), and the code host's
and the tracker's tokens (which `logins check` also tests for still working). The example
pack declares `git`, with its fix.

## The pack kit

A code host connection is mostly the same whatever the host: a card's branch and worktree,
its draft, Ship, the sight a shipping card is watched by, review cards, the brief, the verbs,
the requirement rows and the guard. The pack kit (`keel/packkit/`, c-735) holds all of that
once, so a pack on the kit is only what is really about its host: how to talk to it (its
**host layer**) and its words. The GitHub pack is on the kit.

| Module | What it holds |
|---|---|
| `keel/packkit/layer.py` | the contract: `Repo`, `HostConfig`, the operations a layer has (`OPERATIONS`), the shapes it hands back, and `check_layer` |
| `keel/packkit/pack.py` | which pack the kit runs for: `bind(<the pack's folder>, <its layer>)`, and the pack's words |
| `keel/packkit/errors.py` | the only errors a layer raises: `HostError` (with the host's `status`), `Missing`, `SignedOut`, `NotFound`, `OutsideChange` |
| `keel/packkit/card.py` | the card through `kb`, the space's repos and where each lives on the host, the card's branch and changes, git with a clock |
| `keel/packkit/shared.py` | which branches are shared, and a card's base |
| `keel/packkit/cut.py`, `keel/packkit/pulls.py`, `keel/packkit/ship.py`, `keel/packkit/sight.py`, `keel/packkit/review.py`, `keel/packkit/brief.py` | `worktree`; `pr`, `publishable`, `publish`; Ship; `ship poll`, `diff`, `down`, `reap`, `mine`; review cards; the brief |
| `keel/packkit/verbs.py` | one function per executable, and `run`, which answers in one line and never a traceback |
| `keel/packkit/ready.py` | what every pack's requirement checks share: the row, the space's repos, the clock |
| `keel/packkit/read.py`, `keel/packkit/guard.py` | the guard: the shell reader, and the judge over a pack's `GuardPolicy` |
| `keel/packkit/cli.py` | a transport a layer may use: a host's command line tool, run with a clock and never a prompt, a secret-named variable's value taken out of its words before a failure is said (r1.F5) |
| `keel/packkit/rest.py` | the other transport: a host's HTTP API, with the sign-in git keeps for its address, no redirect followed, every password it holds taken out of the host's words before a failure is said (r2.F4); an answer is JSON, or text when asked (`text=True`, a diff) |
| `keel/packkit/world.py`, `keel/packkit/standin.py`, `keel/packkit/conformance.py`, `keel/packkit/lifecontract.py` | the conformance suite: a fake host as data, the reference layer over it, and the three contracts a pack subclasses |

**The host layer** is one module in the pack's folder (GitHub's `packs/github/gh_layer.py`).
It declares `KIT`, the kit version it was written for, and `HOST`, a `HostConfig`: the host's
name (every sentence's word for it) and how one says a thing is there ("on GitHub"), a pure
address parser (`address(remote_url, clone)`, so `act links` asks nothing of the host), a
change's address (`pr_url`), the ref a change's head is fetched from, what a house is told a
draft is, the host's own sentences (`say`, over the kit's defaults), and the modules of its
requirement checks (`ready`) and its guard's policy (`guard`). Its operations each take a
`Repo` (prints as `owner/repo`, carries `base`, the host's address, and `clone`) and raise
only the kit's errors: `find_open`, `get`, `open_pr`, `set_ready`, `set_body`, `said`,
`checks`, `comment`, `reply`, `post_review`, `review_requests`, `mine`, `default_branch`,
`protected`, `account`, `signed_in`, `access`. A change comes back as `{id, url, draft,
title, state, head, branch, base, own}` (and `author`, `updated` where the host says them); a
comment as `{kind, id, author, bot, body, at, updated, path, line, parent, reply_to,
resolved}`, where `parent` is the line comment it answers and `reply_to` the one a reply goes
under (so reply placement is the layer's, never kit logic); a review as `{id, author, bot,
state, dismissed, body, at}`; a check as `{state, name, url, at}`. `said` reads only the parts
it is asked for, so Ship's reply thread asks no more of the host than it needs. The kit never
starts a host process or opens a socket itself: it calls the layer.

`check_layer` names, in one sentence, a layer that lacks an operation, has no `HOST`, or was
written for another kit (the kit carries `VERSION`; it changes only by adding).

**How a pack reaches the kit.** Each executable is a shim of a few lines: it puts its own
folder and Keel (`KEEL_HOME`, which every verb, the guard and the requirement checks are
given, `packsetup.pack_env` and `keel/doctorpacks.py` included; the folder two up when it is
not set or holds no Keel) on the path and calls
`verbs.run(<verb>, argv, pack=<its folder>, layer=<its layer>)`, or, for `guard`,
`guard.main(argv, pack=<its folder>, policy=<its policy>)`. So the pack's folder comes from
the shim, never from where the kit's files are: the guard knows the pack's own `publish` and
`pr` by the pack's folder, and the brief names the pack's own `pr`. The guard loads only its
policy and the kit's reader and guard, as before (about 30 ms a call).

**The conformance suite** (`keel/packkit/conformance.py`, `keel/packkit/lifecontract.py`) is
what every pack on the kit is held to, as four mixins its `<pack>/tests/test_conformance.py`
subclasses with `unittest.TestCase`:

- `HostContract` holds the pack's REAL layer against a `World` (`keel/packkit/world.py`: a fake
  code host as plain data that records every write, and never holds a real credential), served
  by the pack's own **stand-in hook** as its host would serve it: the GitHub pack's is a `gh` on
  the test's PATH that answers from the world (`packs/github/tests/ghworld.py`), the Gitea
  pack's an HTTP API on 127.0.0.1. It holds the shapes, the states (one the host does not name
  is `unknown`), drafts, forks (never the card's), what was said in the kit's shapes, which line
  comments are resolved, reading only the parts asked for, where a reply lands, a review posted
  whole and a finding outside the change refused (`OutsideChange`, with nothing written, whether
  the host refuses that line itself or would post it, c-739), the checks, review requests
  and the account's own changes, the default branch, protection and access, a sign-in that is
  gone (`SignedOut`) and a change that is not there (`NotFound`), a write budget (only the
  contract's writes: never a merge, a close, a delete or a push) and a token marker found in
  nothing the layer returns or raises. The budget holds only because a stand-in records as an
  `unknown` write every method, path and edit field it does not implement (a DELETE, a PUT, a
  pull request's `state`, a `pr edit`, `pr ready` or `pr comment` flag past what the layer sends; `--method` and `-X`, joined to their value or not, read on every
  `gh api` path), so a layer that closes or deletes fails it: each pack's `test_*_budget.py`
  runs the budget test against a deliberately bad layer to prove it (r1.F2).
- `GuardContract` holds the refusals every guard on the kit makes: the pack's own `publish`, and
  `pr --ready`, by every path form, a forced, deleted or wide push, the sign-in, a research or
  review card's push and `pr`, a card that cannot be read, a line that cannot be read, in
  process and through `bin/keel-house-guard`. A verb handed to a shell or to Python as a
  script (`bash <pack>/pr <id> --ready`, `sh`, `zsh`, `env bash`, `python3 -W x`, a relative
  path, `./`, `..`, or a bare name after a `cd` the guard can follow, one to a written path) is
  judged exactly as the verb run itself (c-738,
  `run_by_forms`), and so is a command word the shell fills in whose words xargs adds
  (`printf 'pr merge 5' | xargs "$TOOL"`, `filled_fed_forms`; with no feeder, `"$PY" "$SCRIPT"`
  stays open, `FILLED_OPEN`, r1.F1), and so is git run through xargs with no subcommand written, whose
  subcommand would come from the feeder (`echo 'push -f' | xargs git`, `xargs -0 git`,
  `xargs -I{} git {}`; `xargs git add` and `xargs git rm` stay open, `git_fed_forms`). Through
  the hook each refusal's sentence is checked, not only its exit, since the hook cannot read a
  card there and that alone holds every form of the pack's `pr`. The pack's `pr` fed by xargs is
  refused (`fed_own_verb_forms`, r1.F3), and honest interpreter lines stay open, in process and
  through the hook (`honest_interpreter_lines`, r1.F6: `bash ./build.sh x`, `python3 -m pytest`,
  `sh -c 'echo pr'`, a bare `pr` outside the pack's folder). Behind all of it the verbs refuse
  themselves: `pr --ready` always, and `publish` outside the user's tap. Three gaps are on record,
  each held by those two refusals in the verbs (`verbs.pr`, `pulls.refuse_unless_shipping_tap`):
  - A `cd` the guard cannot follow (to a target the shell fills in, `cd "$P"`; `cd ~`; `cd -P x`;
    `pushd`) leaves its working directory stale, so `cd "$P" && bash pr c-1 --ready` resolves the
    bare name against the wrong folder and passes the guard (r2.F6).
  - `bash -c 'cd X'` moves the guard's working directory though the `cd` runs in a subshell, so a later `./pr` is resolved under X.
  - A flag the shell fills in before a script (`bash "$FLAGS" <pack>/pr --ready`) hides where the script stands, so it is not judged as the verb.
- `VerbsContract` runs the pack's real executables through `keel/adapters.py` on a real board in
  a scratch install, over a card's whole life (cut, brief, the house's push, the draft,
  publishable, Approve, a sight, Ship and a second Ship that posts nothing twice, the links and
  the reap): the only writes are the contract's, and the only push is the card's own branch.
  Approve and each Ship run inside the user's tap, through the board, as `kb` runs them. It
  also holds the verbs refusing themselves, with no guard in front (c-738 r1.F2, r1.F3): `pr
  --ready` at every stage, and `publish` run with no nonce, a made-up one or a stale one, at
  building, review and shipping, the user's tap open or not.
- `ReviewsContract` (r1.F1) runs them over a review card's whole life, for a pack that claims
  `reviews` (the scan, the detached checkout, the brief, the poll and the review posted once):
  one review written, and no push at all. Both lives stand on `LifeHarness`, the scratch
  install and its hooks, so a pack gives the hooks once and subclasses each life it lives.

The kit's own stand-in (`keel/packkit/standin.py`) is a layer over a world in the test's own
process: the contract made runnable, held by the same `HostContract` (`tests/test_packkit.py`).

**`keel pack check <dir>`** (`keel/packcheck.py`) runs a pack's suite in a process of its own and
requires the contracts its claims call for: a code host (`[capabilities] codehost`) holds
`HostContract` and `VerbsContract`, one that claims review requests (`reviews`)
`ReviewsContract` too, and a guard (`[guard]`) `GuardContract`. A code host with no review
requests, as `keel new pack --kit` writes one, can pass. It says in one line
whether the pack passes, how many tests ran, and which contract it holds or lacks. A suite that
gives no answer in 30 minutes (`SECONDS`) fails it with that one sentence, never a traceback (r1.F7).

**The words.** The kit spells no noun of its own: every sentence says the pack's `[terms]`
(`change`, `changes`, `change_short`) and the host's name, so the GitHub pack's sentences are
what they were, byte for byte, and the noun guard (`tests/nouns.py`) holds the kit with no
exception.

**Parity.** The move of the GitHub pack onto the kit changed no behaviour: its suite changed
only at imports and patch targets, and a parity capture taken before the move (every gh call
and what it was handed, every git call, every verb's output, the board's notes and options,
over a card's whole life and a review card's whole life) matched after it.

## The GitHub pack

`packs/github/` is the code host a new install can turn on (c-689, step 13 of c-668): pull
requests on github.com, driven through `gh`, GitHub's own command line tool, and plain
`git`. It is a code host, and since c-730 it brings you the pull requests that wait on your
review ("Review requests", below). It declares `codehost` and `reviews`, with the `reviews`
provider route (the Reviews gear): no tracker, no CI page. Reviews start off: its `[space]`
says `review_scan = false`, so a space on it files no review card until the user turns them
on (Where finished work goes asks, [onboarding](89-onboarding.md)). A space on it draws
Keel's general flow ([flows](64-flows.md)): the house pushes its own branch and opens a
draft, Approve outcome marks it ready, the watcher reads comments and checks while the card
waits at shipping, Ship pushes the house's fixes and posts the replies kept, and the card is
done when the pull request is merged ON GITHUB, by a person.

**One seam.** Every call to GitHub is `gh` as a subprocess (`gh_cli.run` in
`packs/github/gh_cli.py`): given a clock (30 seconds a call), never a prompt
(`GH_PROMPT_DISABLED`), never the verb's own stdin, and always asked for github.com by name
(`-R github.com/<owner>/<repo>`, `--hostname github.com`), so a `GH_HOST` in the environment
sends nothing elsewhere. There is no HTTP client and no Python dependency. A failure is the
contract's: exit 1 and ONE line on stderr, `<verb>: gh pr view failed: <gh's own first
sentence>`, with colour, usage text and line breaks taken out; gh not installed, gh not
signed in, GitHub's not-found answer, a timeout, an answer that is not JSON and anything
unforeseen each have their own sentence or class, and none is a traceback (the kit's `verbs.run`).

**No secret.** gh holds the sign-in. The pack asks gh to act as the signed-in account and to
say whether it is signed in and who as; it never asks for the credential, reads none from
the environment and stores nothing. The account's name appears only in a requirement's
answer. The suite runs every verb with a token in the environment and finds it in nothing
the pack prints, runs or records.

**What it needs** (`[[requires]]`, each a check with a reason `why` and its own `fix`,
"A requirement's own fix" above; the check is `./ready <name>`, exit 0 when ready):

| Requirement | Ready when | When it is not |
|---|---|---|
| `gh` | gh is on the path | the install line to copy, for macOS (`brew install gh`) and Linux; the pack never installs anything |
| GitHub sign-in | `gh auth status --hostname github.com` passes | `gh auth login`, a terminal sign-in the page walks through; a check that could not finish says so and is not called signed out |
| GitHub address | every repo of the space (`KEEL_SPACE_REPOS`) has a github.com remote, as its config writes it or as git resolves it | which repo and which address, and the two ways on |
| GitHub access | GitHub says the account's permission on each of those repositories is write, maintain or admin (`gh repo view --json viewerPermission`) | not found: "You are signed in to GitHub as A, which cannot see O/R", with `gh auth switch`. Read-only: "which can read O/R but cannot push to it". Anything else (a rate limit, a server error, the network): "could not be checked", never the account's fault |

A space with no repo yet passes the last two, so the pack can be turned on before the first
clone. The access check keeps every gh call, the account's name included, inside the ten
seconds the engine gives a check. Its one first-run step, "Connect GitHub" (`[[setup]]`,
`packs/github/setup/connect.md`), is done when the four pass. `logins check` gives Keel's
Logins list one row, the sign-in: `good`, `expired` (gh says it has none that works, fix
`gh auth login`), `missing` (no gh) or `unknown` (it could not be asked).

**Where a person sees the fix.** The engine carries it (c-688): `packs.checks` returns each
requirement's `fix`, and its `command` and `done_when` where the pack wrote them, so a
failing check shows its fix in Setup's pack row, in the pack's own first-run step ("Connect
GitHub") and under the pack's line in `keel doctor`. The sign-in alone has a `command`
(`gh auth login`), since no one line installs gh on every system, sets a remote without the
repo's own address, or grants access; three of the four say `done_when`. `pack.toml` holds
the GENERAL sentence for each. The SPECIFIC ones (which account, which repo, which address)
come from `./ready`, run in the pack's directory, which prints the four as JSON,
`[{name, ok, why, fix}]` (`packs/github/gh_ready.py`); the engine does not read those yet.

**The verbs.** The same shapes as the work pack's ([the work adapter](60-work-adapter.md)),
held by the pack's own suite (`packs/github/tests/`), which hands the sight to the engine's
reader (`shipwatch.fold`) and runs the executables through `keel/adapters.py` on a real board:

| Verb | On GitHub |
|---|---|
| `worktree` | one worktree per repo where Keel puts a card's everywhere else (`adapters.worktree_dirs`), on the branch Keel names (`[spaces.<name>] branch`), cut from the remote's base (`options.base`, else the repo's default branch) with `--no-track`, so a bare `git push` there cannot be aimed at the base |
| `brief` | the house and the ending |
| `guard` | reads each command a house is about to run and allows only gh's reads (The guard, below); the pack has no `deny` verb |
| `pr <id> --draft`, `--body` | `gh pr create --draft` from the card's branch into its base, the title the card's and the body handed on stdin (the repo's ```copy block under `## PR body` in the record, else the card's brief); one found open on the branch is recorded instead. `--body` is `gh pr edit --body-file -`. `--ready` is refused by the verb itself (the kit's, c-738 r1.F2): nothing in the engine runs it, and only `publish` marks a draft ready |
| `publishable` | the branch is on the remote (`git ls-remote`) with the local head, and a pull request is open from it |
| `publish` | Approve outcome: every repo's pull request read, then every draft marked ready, one note, `{pr, url, draft, shipping: true, heads}`. On the kit it runs only inside the user's tap, Approve outcome or Ship, at every stage and for every kind of card: the nonce Keel hands it (`KEEL_PUBLISH_NONCE`) must match the digest the board keeps on the card (`options.publishing`), or it refuses (c-738 r1.F3, `pulls.in_tap`). The verb takes the nonce out of its environment before it starts anything (`pulls.take_nonce`), so no git, host tool or `kb` it runs is handed it, and every git call the kit makes runs with hooks and fsmonitor off (`card.NO_HOOKS`), so a hook a house plants in its tree (`.git/hooks`, `git config core.hooksPath`) never runs inside the user's Approve or Ship (r2.F2). So a repo's own pre-push hooks do not run on a kit push either: a house could plant one, and it would run with the user's credentials. git-lfs uploads through that hook, so before the Ship pushes a branch whose tree has a `filter=lfs` attribute, with `git lfs` on the PATH, the kit runs `git lfs push <remote> <branch>` itself, hooks off, and a failure stops that push in one sentence. A repo with that attribute and no git-lfs installed is refused, saying how to install it, since its push would carry the pointers without their objects. A repo not on LFS sees nothing new (`ship.lfs_push`, r2.D1). A marker older than `pulls.TAP_SECONDS` (15 minutes, by its `at`) opens nothing, so one a killed `kb` left is never honoured, and Approve and Ship hand the verb the tap's budget (`merging.tap_budget`, below the deck's own wait) as its timeout, so `kb` stops a slow publish and clears the marker itself (r2.F3) |
| `publish --answer` | Ship (below) |
| `ship poll` | the sight: `gh pr view --json` for state, draft, head, base and the head's checks; the conversation, the line comments and the submitted reviews through `gh api --paginate`; which threads are resolved through `gh api graphql`, paged to the end |
| `ship diff`, `method`, `down`, `reap`, `mine` | the diff from the clone; `rules/comments.md`; nothing to stop; a done card's clean worktrees removed with `git worktree remove`, never forced, never the clone itself; the signed-in account's open pull requests (`gh pr list --author @me`) matched to cards by branch |
| `act` | no card verbs; the links (`pr`, `prs`, `unpublished`) built from the card and the clone's address, with nothing asked of GitHub; `act do reviews` with the Reviews gear's `set_auto_review`, `set_review_model` and `scan_now`, written through `keel/reviewsettings.py` for the space `KEEL_SPACE` names |
| `review scan`, `review <id> poll` | the pull requests that wait on your review, and where one review card's stands ("Review requests", below) |
| `providers/reviews` | the Reviews gear: the space's auto review and review model, the models, and when the drain last looked |

**Review requests** (c-730, the kit's `keel/packkit/review.py` over GitHub's layer). The pack's half of review cards, in
the work pack's shapes ([the work adapter](60-work-adapter.md), "A review card"), so the
drain's `keel/reviewcards.py` reads it unchanged:

- `review scan` asks each of the space's GitHub repos (`KEEL_SPACE` names the space; by hand,
  the one space on the pack that asks for reviews) with gh's own search, `gh pr list -R
  github.com/<owner>/<repo> --search review-requested:@me --state open --json ... --limit 100`,
  and prints `{prs, open_groups}`: each row `{key: <repo>:<number>, repo, pr, title, author,
  description, created, updated, head, branch, base, url, group: null, fork}`. GitHub has no
  story to group by, so `open_groups` is empty and every card reviews one pull request. A
  fork's pull request is a row with `fork: true` (`isCrossRepository` not false; a missing
  answer is a fork), which the drain never starts by itself and whose house reads its code,
  confined, never runs it and loads none of its settings (r1.F1, r2.F3, [the
  drain](30-drain.md), [houses](20-houses.md)); its brief says so (the kit's `brief.FORK_HOUSE`). A repo whose
  remote is not on GitHub is not asked. A repo GitHub will not answer for (no access, a rate
  limit, a timeout) is skipped with a line on stderr and the others are scanned (r1.F3); a
  scan where every repo fails is refused, never an empty list.
- `review <id> poll` is `gh pr view --json` read as `{state, head, url}`; a state GitHub does
  not name is refused, never read as open.
- `worktree` for a review card (`options.review_key`, or `kind = review`) is ONE worktree
  DETACHED at the pull request's head as GitHub has it now, fetched from GitHub's own
  `refs/pull/<n>/head` (so a fork's arrives the same way) with its base: nothing in it is a
  branch of anyone's. A re-review moves it to the new head. It records `options.worktree` and
  `options.review_head`. The brief is the read-only house and the review ending; the guard
  refuses a push and the pack's `pr` to a review card's house, as to a research card's; `pr`
  and `publishable` treat it as having no pull request of its own.
- Approve outcome hands `publish --answer` the review you kept (`keel/reviewround.py`), and
  the pack posts it as ONE review through GitHub's pull request review API (`gh api --method
  POST repos/<owner>/<repo>/pulls/<n>/reviews --input -`): the kept findings inline at their
  lines (`side: RIGHT`), the summary as its body, the verdict as its event (`APPROVE`,
  `REQUEST_CHANGES`, else `COMMENT`) and `commit_id` the head the house reviewed. `gh pr
  review` was not used: it takes no line comments. One call, so it lands whole or not at all.
  Its body ends with a hidden marker, `<!-- keel:review <card> round <n> -->`; a retry first
  reads the pull request's reviews by the signed-in account, and one carrying the marker is
  the one that landed, so nothing is posted twice. When GitHub refuses a finding's line (one
  not in the change: HTTP 422), the review is posted again with every finding in its body,
  each named `path:line`; any other failure is said once and nothing more is posted. The
  landed review is looked for first and recorded whatever the pull request's state (r1.F4);
  only a new post needs it open, so one that is no longer open gets nothing new. The card then
  carries `options.review_posted` (`head`, `round`, `verdict`, `severity`, `ledger`, the review's id).
- Reviewing reads, so `gh`, the sign-in and the GitHub address serve `reviews` too; write
  access serves only the code host.

**Whose pull request.** gh's `--head` matches a branch name in anyone's fork, so on a public
repository a stranger could open a pull request from a fork branch of a card's name. The
pack reads every match and takes only one GitHub says is not cross-repository
(`isCrossRepository` false, GitHub's own answer, which holds after a rename or a transfer
where a comparison of names with the clone's address would not; a missing answer is not a
yes): a fork's is never recorded as the card's, marked ready, replied on or watched. A
state GitHub does not name (`unknown`) is never read as open: the poll, Approve and Ship
each refuse on it.

**The sight.** GitHub's `OPEN`, `MERGED` and `CLOSED` are said as open, merged and declined.
What counts as said: a general comment, a line comment, and the words a review was
submitted with; the author's own, a `Bot` account's and a resolved thread's are left out. A
reviewer's standing review is their newest approval or request for changes, and a dismissed
one is none. The checks are the head commit's check runs and commit statuses as one word.
GitHub numbers the three kinds of comment separately, so a comment's `id` says its kind,
`g<n>`, `l<n>` or `r<n>`; the engine takes any id (it makes the handle `c` and the id:
`cg101`, `cl201`, `cr301`) and Ship routes a reply by that kind, so one number in two of
GitHub's id spaces is two comments and sends no reply astray. A reply's `parent` is the
HANDLE of the comment it is under (`cl201`), the name the house is told, and comments come
in the order they were said.

**Ship.** Before anything leaves, for every repo of the card before the first push, in
this order: every reply's handle names one of the card's pull requests; when there are
replies, gh says which account is signed in; every pull request the Ship would touch is
read and is still open, from the card's own branch and from the repository itself (one
merged, closed, from another branch, from a fork or in a state GitHub does not name refuses
the whole); every branch is the card's own and its worktree is on it; the branch is still
on the remote (one deleted after a merge is a refusal, never made again, and a remote that
cannot be asked is a refusal too). Then the push, a plain fast-forward of the card's branch
to itself; a push that fails names its repo and the repos already pushed. Then a draft is
marked ready; then the replies. Each reply ends with a hidden marker, an HTML comment naming
the handle it answers and a digest of its words (the kit's `ship.marker`), and that marker, written
by the signed-in account (the one that posts, whoever opened the pull request), is how a
retry after a failure halfway knows what already landed.
Words are never compared: the same sentence to another item is posted, and a sentence the
author typed by hand stands in for nothing. A reply to a line comment goes into that
comment's thread (under its first comment), any other is a general comment.

**Shared branches** (the kit's `keel/packkit/shared.py`). Nothing cuts a card on, pushes, or opens a
pull request from a branch that is shared, and a branch is shared when any of these says so:
a usual name (main, master, trunk, develop, development, staging, production, release, or
anything under `release/` or `hotfix/`); the card's base; GitHub's default branch of the
repository, read from GitHub and never from the clone; or a branch GitHub reports
protected, whatever its name. When GitHub cannot say which branch is the default, or
whether one is protected, that is a refusal too: nothing is cut, pushed or opened on a
guess, `main` is never assumed, and the sentence ends "try again". The base a card is cut
from and its pull request opens into (`shared.base_in`) is `options.base`, else GitHub's
default branch: a verb that writes (the cut, the draft, Ship) takes GitHub's answer or
refuses, and a verb that only reads (the brief, the diff, how far behind) gives GitHub five
seconds (`shared.READ_SECONDS`) and then falls back to the clone's record. Every branch and base name read from a card or from GitHub is checked
once as a name git accepts (the kit's `card.ref_name`: `git check-ref-format --branch`, and no
leading `-`, `:` or `+`), and every fetch names its branch in full (`refs/heads/<name>`),
so a base such as `--upload-pack=x` never reaches git.

**The guard** (`packs/github/gh_fence.py`, GitHub's `GuardPolicy`, over the kit's guard and reader, `keel/packkit/guard.py` and `keel/packkit/read.py`; the pack's `guard` verb; "A pack's guard" above
says how the engine asks it). `gh` in a house's shell is signed in as the person it works
for, so the pack READS each command before it runs. It parses the line as a shell would; it
never matches text, which is why a commit message, a path or a grep that only mentions
`gh pr merge` is not a command, and why a write is a write however it is spaced, quoted or
wrapped. (Two earlier fences here were lists of permission globs: wide ones refused honest
lines such as `git commit -m "tighten the config loader"`, narrow ones let a quoted
`publish` path through, and neither was ever shown to the harness. They are gone, and the
pack hands out no deny list.)

- **How a line is read.** Split into simple commands on `;`, `|`, `&`, `&&`, `||`, line
  ends and brackets, with quotes, escapes, redirects and here-documents read as a shell
  reads them. It looks inside `$( )`, backticks, `<( )`, `${ }`, `bash -c`, `sh -c`,
  `zsh -c`, `eval`, `env -S` and a here-document or here-string fed to a shell, and past
  `env`, `command`, `sudo`, `xargs`, `time`, `nohup`, `exec`, `nice`, `timeout`,
  `function`, `coproc` and leading `NAME=value` words. An array (`NAME=(...)`) is not a
  command, and `$(( ))` is arithmetic. One rule covers a command word the reader cannot fully
  know (a variable, a substitution, `$'...'`, a pattern holding `{`, `?`, `*` or `[`, or a
  mix of them). When what is written can be shown to be gh or git (`g?`, `{gh,x}`, nested
  brace lists written out) it is judged as that tool. Otherwise, when the next bare word
  (past `-R` and its value) is one of gh's distinctive groups (`pr`, `issue`, `api`,
  `auth`, `repo`, `release`, `secret`, `gist`, `workflow`, `ruleset`), it is judged as a
  gh line: `$GH pr view 12` is open, `$GH pr merge 1` and `g[[:alpha:]] pr merge 1` are
  refused, and so is `./tool-*.sh pr merge 1`, which is probably not gh (an accepted
  cost, on record in the suite). The groups other tools share (`run`, `config`, `status`)
  are left out, so `$NPM run build` is not gh. Otherwise, when the word could be git and
  `push` follows git's global flags, it is judged as a git push. Otherwise, when xargs adds
  its words and the word could be gh or git, it is refused (c-738): `printf 'pr merge 5' |
  xargs "$GH"`, `xargs $(which gh)`. With no feeder it is not (r1.F1): `"$PY" "$SCRIPT"`,
  `$EDITOR "$file"` and `"$CMD" "$@"` stay open. Otherwise it is some
  other command. Only `?` and `*` are matched as patterns; a bracket is unknown, never
  harmless. A brace word is sized before any of it is written out, since the guard runs to
  a clock: each pair's own commas plus one, multiplied. One over 256 characters, 16 brace
  pairs or 64 words is not written out, and as a command word it is refused outright,
  whatever follows it (as an argument, `echo {1..100000}`, it is nothing). A word with a written base name (`"$VENV"/bin/uv`) is judged by that name,
  and the rest of the line is judged either way. A line it cannot read
  (a quote that never closes, a nesting too deep) is
  refused when it names `gh`, a push or the pack's own verbs, the rule `keel/flowfence.py`
  uses for a push.
- **gh: only reads are allowed**, so it is deny by default in fact, and a new gh's new
  write is refused without anyone adding it. After the global flags (`-R`, `--repo`,
  `--hostname`) come the group and the verb, and the whole list is `gh_fence.READS`: `pr`
  view, list, checks, diff, status; `issue` view, list, status; `run` view, list, watch;
  `workflow` view, list; `repo view`; `release` view, list; `label list`; `cache list`;
  `search`; `status`; `auth status` without the token; and `gh api` as a GET that sends
  nothing (no `-X` or `--method` but GET, no `-f`, `-F`, `--field`, `--raw-field` or
  `--input`, written before the word `api` or after it, never `graphql`). Asking gh for
  its help runs nothing and is open: a bare `gh`, `gh --version`, `gh help`, `gh version`,
  and for a group gh ships a `--help` that is no flag's value or a `-h` as the last word
  (an extension's own `--help` stays refused).
  Every other gh command is refused with one sentence naming the verb and the way that is
  the house's where there is one (`pr <id> --draft`, `pr <id> --body`, `kb verdict`).
- **git push** is refused with a force (leased or not), delete, mirror, all, branches,
  tags or prune flag, shortened (`--del`, `--forc`) or in any cluster of short flags, with
  a refspec holding `:`, `+` or `*`, with a refspec the shell builds, and with more than
  one refspec. `git -c` setting an alias, a push or credential setting or a remote's push
  refspec is refused, and so is `git credential`. git through xargs with no subcommand
  written (`xargs git`, `xargs -I{} git {}`) is refused, since the feeder would choose it;
  `xargs git add` is judged as `git add` (c-738). git whose subcommand the shell fills in
  (`git "$@"`, `git "$SUB"`, `git $1`) is refused, fed or not, and a shell's `-c` body run
  under xargs is fed as the shell is, so `xargs sh -c 'git "$@"' _` is refused (r1.F4).
- **The pack's own verbs.** `publish`, and `pr` with `--ready`, are refused however the
  path is quoted or reached (`"$KEEL_HOME/packs/github/publish"`, the `adapters/` link,
  `cd` then `./publish`, `python3 <path>`). A shell or Python handed the verb as a script
  (`bash <path>/pr <id> --ready`, `sh`, `env bash`, `bash -o posix`, `python3 -W x`, a bare
  `pr` after a `cd` to a written path) is judged as the verb itself, past the interpreter's own flags (`-c`,
  `-s` or `-m` mean it runs no script file); this is judged beside the older reading of the
  shell's words one by one, never instead of it (c-738). `pr --draft` and `pr --body` stay a building
  house's. Approve outcome is not behind the guard: the engine runs `publish` as a process
  of its own (`keel/adapters.py`), never through a house.
- **A research card** loses every push and every form of the pack's `pr`. The guard reads
  the card (`kb show`, three seconds) only for a command of that shape, and a card it
  cannot read holds that command.
- **A card at shipping**, and a push to a shared branch of the flow, are the engine hook's
  own refusals ([houses](20-houses.md)), made after the pack has allowed the command; the
  pack does not repeat them.

**What it does not read**: a script file the house writes and runs, an alias, a variable that holds a whole command, a command piped into a shell, `find -exec` or another program that runs gh, a `case` pattern inside `$( )`, a brace sequence or a variable inside a brace list, and a flag whose value is taken for the verb
(`gh pr --body view merge 1`). **It is a fence for an honest house, not a wall.** The walls are GitHub's:
the repository's branch protection and what the signed-in account may do.

The suite holds three lists written by hand (`packs/github/tests/test_gh_fence.py`):
`WRITES`, every spelling that must be refused; `READS`, what a house may run, the commands
the rules name among them; and `FREE`, lines that only mention the words. A fourth, short
one, `REFUSED_NOT_WRITES`, keeps the price on record: honest lines that are refused (a
read outside the list such as `gh run download`, a push of a name the shell builds, gh
under xargs), and a fifth, `NOT_READ`, holds three spellings known to be open (a
directory named like a gh group after a variable, a brace sequence, a variable inside a
brace list). The guard's one stateful path, the card read through
`kb show`, runs against a real scratch board (`test_gh_verbs.py`). Each list is held
against the reader in process AND through the real hook, `bin/keel-house-guard` run as a
subprocess with the PreToolUse JSON, which is the contract the harness itself runs. One
call costs about 30 ms on top of the hook's own 50 (two Python starts; reading the line
is microseconds), on every Bash call a house on this pack makes.

**What it never does**, each held by a test that RUNS every verb through a card's whole life
against a stand-in `gh` and a recording `git` and counts everything that writes:

- **It never merges, closes or deletes.** The only gh calls that write are `pr create`,
  `pr edit`, `pr ready`, `pr comment`, a reply to a line comment, and, on a review card's
  Approve, the one review (`POST repos/<owner>/<repo>/pulls/<n>/reviews`).
- **It never forces a push.** The only push is one refspec, the card's own branch to itself,
  with no flag; a branch rewritten on the remote refuses the whole Ship, a push the remote
  rejects is said and not retried harder, and the `lease` Keel hands is ignored.
- **It never pushes or opens a pull request from a shared branch** (above).
- **It never writes to a pull request that is no longer open.**
- **It never installs gh or signs anyone in.**

**Limits, said plainly.**

- github.com only. GitHub Enterprise Server and a remote written through an ssh host alias
  (`git@work-alias:owner/repo`) read as "not a GitHub address".
- A draft pull request needs a repository GitHub allows drafts in. Where it does not, `gh pr
  create --draft` fails with GitHub's own sentence and the card cannot be staged.
- `git` must be able to push to the remote: gh being signed in does not make git use that
  sign-in over https. A push that would ask for a password is refused at once
  (`GIT_TERMINAL_PROMPT=0`) and says to run `gh auth setup-git`. No requirement checks this
  ahead of time.
- Every cut, draft and Ship asks GitHub two things first (the default branch, the branch's
  protection), so none of them works while GitHub cannot be reached.
- No `pr --flow` (`flow_pr` is not declared), so a flow whose move `opens` a second pull
  request is refused for a space on this pack.
- `ship mine` is told no space. With one space on the pack it reads that space's repos; with
  several, the ones that list a repo the handed cards name.
- Resolved threads are read up to 3,000 threads and 3,000 comments in one; past that the
  poll is refused rather than read as whole.
- A general comment has no thread on GitHub, so a reply to one is a new general comment.
- A reply's marker is the handle and a digest of the words, as Keel's own record of a posted
  reply is: the same words to the same handle in a later round are taken as already said.
- Markers are found under the account gh is signed in as. After `gh auth switch` to another
  account, a retry no longer sees the first account's markers and posts those replies again.
- The create path (`gh pr create`), the ready mark, the edit, the replies, the fork filter,
  the protection read, the account read and the graphql paging are proven against a stand-in `gh`, not against
  GitHub: nothing in the suite or in the building of this card wrote to a real repository,
  and the one real read was a pull request list. The same holds for the review requests
  (c-730): the search, the review post and its 422 fallback are proven against the stand-in
  only, and proving them on a real repository with a real review request is the owner's
  attended step.

## The Gitea pack

`packs/gitea/` is a code host on the pack kit (c-735): pull requests on a Gitea, through its
API (`/api/v1`) at the address each repo is cloned from, and plain git. It ships no tracker,
no stored sign-in and nothing to install. It is the kit's second host, and what a host is
once the kit carries the rest: three modules and their sentences.

| File | What it is |
|---|---|
| `packs/gitea/gt_layer.py` | the host layer, over the kit's HTTP transport (`keel/packkit/rest.py`) |
| `packs/gitea/gt_ready.py` | the five requirement checks and the Logins rows |
| `packs/gitea/gt_fence.py` | Gitea's `GuardPolicy`: `tea` (refused outright), and a call to its API by `curl` or `wget` |
| `packs/gitea/tests/giteaworld.py` | its stand-in: a `World` served as Gitea's API on 127.0.0.1 |

**The sign-in is git's.** The transport asks `git credential fill` for the address (git is
told never to prompt), keeps the answer in memory for the length of the verb, and sends it as
HTTP Basic, which a Gitea takes with a password or an access token in place of one. It never
writes, prints or logs it, and never hands it back to git. A redirect is never followed: the
sign-in was asked for one address and goes to no other. An access token may do only what it
was made for, and Gitea refuses a call outside its scopes in its own words, which the layer
reads as `ScopeMissing` and turns into one sentence naming the token to make
(`write:repository`, `write:issue` and `read:user`).

**Gitea's words, in the kit's.**

- **An address** is http or https: its last two parts are `owner/repo`, and what stands
  before them is where Gitea is served (a Gitea may live under a path). An ssh address does
  not say where the API is, so a repo cloned over ssh cannot use this pack.
- **A draft is a title.** Gitea has no draft of its own kind: a pull request whose title
  starts `WIP:` or `[WIP]` is one, and Gitea refuses to merge it (the layer reads it so from the title as well as from a `draft` field, r1.F4). So a draft opens with
  `WIP: ` before the card's title, and marking it ready takes the mark off; one Gitea still
  calls a draft after that is refused. A house is told so in its brief (`draft_note`).
- **A pull request's state** is `open`, `merged`, or `declined` (closed without merging);
  `own` is true when the head's repository is the base's.
- **What was said.** General comments are the issue's. A line's comments are listed under the
  review each came in, and Gitea does not say which answers which, so the comments on one
  line of one file are one conversation, in the order they were said, each after the first
  naming the first as its parent. A bot is a name ending `[bot]` or one of Gitea's own system
  accounts. A resolved line comment has a `resolver`.
- **A reply** is posted under the comment it answers (`pulls/<n>/comments/<id>/replies`). A
  Gitea too old for that call answers 404 or 405, and there the reply is a review's
  comment on the same line of the same file, which Gitea shows in the same conversation.
- **The checks** are the head commit's statuses: `failure` and `error` failed, `pending`
  running, anything else passed (a warning is not a failure).
- **A review** is posted whole, its line comments at `new_position`. Gitea posts a comment on
  a line the change does not touch (line 99 of a 3-line file, 2026-10-10), so the layer reads
  the change's diff first (`pulls/<n>.diff`, through the transport's `text` read) and a
  comment on a line no hunk of that file shows, added or context, as GitHub takes them, is
  `OutsideChange`, with nothing posted (c-739); a 422 from Gitea is `OutsideChange` too. The
  stand-in posts any line, as Gitea does, and serves the diff from the world's `changed`. **Review requests** are the open pull requests that
  name the signed-in account among their requested reviewers and that it did not write.

**What it needs** (`./ready`, five checks): git installed; each repo's remote an http or
https address; a sign-in git keeps that Gitea accepts; a sign-in allowed to say whose it is
and to read a pull request's comments (a token made only for pushing is not); and write
access to each repository.

**The guard** (`gt_fence.py`, over the kit's guard and reader). Beyond what every pack's
guard refuses ("A pack's guard" above, the conformance suite's `GuardContract`), tea, Gitea's
own command line tool, is refused outright, reads included (r2.D3): a house reads with git, the
pack's own verbs do the host's writes, and reading tea flag by flag kept leaking (the same short
flag takes a value in one group and none in another). Only help with no other word but one group
runs (`tea`, `tea --help`, `tea -h`, `tea <group> --help`). A command word the shell fills in
(`$(which tea)`, `"$TEA"`) followed by any tea command or alias, anywhere after it, is refused as
tea is (`DISTINCT`, r2.F2; the policy's `distinct_anywhere`, r2.D4, so `"$TEA" --limit 5 pr merge
7` cannot hide its `pr` behind a flag; the GitHub policy leaves it off), and so is one whose words
xargs adds (`printf 'pr merge 5' | xargs "$TEA"`, the kit's rule, c-738). That is fail-closed on purpose: a shell-filled git or docker word followed by a word tea
shares (`"$GIT" clone url`, `$(which git) branch x`, `"$DOCKER" login`) is refused too, and the
refusal says the command word could not be read and may be tea (r2.D1). `curl` or
`wget` with a word holding `/api/v1` is refused, whatever the address and the method, and so
is one run through xargs, whose address is not on the line. git's credential helpers run by
name (`git-credential-store`) are the sign-in's. Its `[guard] tools` are git, tea, curl and wget.
It does not read an address the shell builds whole (`curl "$URL"`), or another program that
speaks HTTP.

**What it does not do.** No tracker, no CI page, no `pr --flow`. It never merges, closes or
deletes. It has been proven against its stand-in only: the conformance suite (all four
contracts, `keel pack check packs/gitea`) and its own tests. Proving it against a real Gitea
is the owner's attended step.

## Drift terms

`make drift` greps every tracked file outside a pack and `docs/` against that pack's
`drift-terms`; a hit fails `make test`. The employer's words are the work pack's, so they
may be written only in `<install>/packs/work/`. `packs.all_drift_terms` is the same lists for the
checks that read them in code: the Atlas's own (`tests/test_atlas.py`), the demo's, and
the demo recorder's sweep. The Atlas's and the demo's read `packs.configured_drift_terms`
(c-722): the tree's lists, then those of the install `KEEL_CONFIG` names, since an owner's
pack lives there once moved. They skip only when neither carries a list. `make drift` reads
the install's packs too (`tests/installdrift.py`, r1.F7): each pack with terms under the
install `KEEL_CONFIG` names is grepped against every file of the tree outside `docs/` and
outside the tree's pack of the same name, and a hit fails it; it says which install it read
and how many terms, never a term, and with no install named it reads nothing and says that
no install's terms were checked. It runs behind the test fence, which drops `KEEL_CONFIG`,
so it reads the install the caller named, from the environment as it was before the fence
(`fence.caller()`, `packs.install_packs(environ)`): read from its own, it once read no install
and passed with the install's words in the tree (c-733). A `~` in `KEEL_CONFIG` is the
caller's `HOME` (`packs.expand_home`). An install named whose terms cannot be read, its
`config.toml` not there, a `drift-terms` that will not read, a packs or pack folder it may
not list or search, or a link there to nothing, fails it, and so does a
`KEEL_CONFIG` that names neither an install's `config.toml` nor the code's own config. The
demo sandbox's `keel.toml` (`demo/sandbox/run` names it), there as a file beside the
`.keel-sandbox` marker its setup writes, passes, saying no install's terms were checked; any
other name, a missing file, or no marker fails. Any grep exit but 0 or 1 (a signal's
included) fails the check, read before anything grep printed. A hit
is printed as its file and how many lines hold a term (`<file>: <n> hits`), never the line's
text, which holds the term: grep is asked only for names (`-l`) and counts (`-c`), and
nothing it prints is echoed but a name it was handed and a number. It is handed only the
tree's files that are there as regular files, so a tracked file deleted before a commit is no
error; a file grep cannot read fails it, named as `<file>: could not be read`, without grep's
own words. The tree's file paths are read against the terms too: a path that holds one is a
hit even with clean contents, and on every line it is printed masked, its terms as `<pack
term>` (the public check's `shown`), or as no part of it at all when Python cannot read a term
as grep does or grep still finds one in what is left.

## Writing a pack

For a user, or their builder, adding an integration:

1. **Start from the example.** `keel new pack <name>` copies `packs/sandbox/` to
   `packs/<name>/` (or, with `--install`, to `<home>/packs/<name>/`), renames it in
   `pack.toml` and its `config.example.toml`, and loads it: the sandbox's `[capabilities]`,
   `[terms]` and `[[setup]]` step come along valid ([Extending Shipyard](63-extending.md)).
   Then keep only the verbs your space needs, and its claims with them. A verb that is
   absent is a feature the space does not have, never an error. For a code host, start with
   `--kit` instead ("The pack kit" above): the verbs are the kit's, and the pack is its host
   layer, its stand-in and its sentences.
2. **Hold to the adapter contract.** Each executable takes the card id, reads the card with
   `kb show <id> --json`, prints JSON (or the brief's markdown), exits non-zero with one
   line on stderr to refuse. Write to the board only through `kb`. The tables in [the work
   adapter](60-work-adapter.md) are the shapes the engine reads.
3. **Keep the engine ignorant.** Every word about your tracker, code host or stack lives in
   the pack: labels come back through `options.json`, `act verbs` and the providers. If
   those words must never leak, list them in the pack's `drift-terms`.
4. **Rules are markdown, enforcement is mechanism.** Put what a house must know in
   `rules/*.md`; put what it must not do in `deny <id>` (permission denies) or, when the
   answer depends on reading the command, in a `guard` verb ("A pack's guard"), never only
   in prose.
5. **Declare, do not vendor.** A tool the pack calls is a `[[requires]]` entry with a check,
   not a copy in the pack, and it says its own `fix`, `command` and `done_when`, so a user
   who lacks the tool is told what to run. Say what the pack provides in `[capabilities]`, and tie each
   check to the capability it serves with `for`, so a missing token shows on the page it
   stops, not as a general warning.
6. **Name it for the space, not the vendor**, so the config never names the vendor either.
7. **Prove it by running it**: a space on the pack in a scratch config (as
   `demo/sandbox/setup` writes one), a card through `worktree`, `brief` and `pr`. A pack's
   own suite is optional; the engine's suite holds the contract. A pack on the kit is done
   when `keel pack check <dir>` passes.
