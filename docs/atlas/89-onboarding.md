# Onboarding

A fresh install (`shipyard init <dir>`, [install](88-install.md)) starts with no repo of the
user's and no pack (only its own repos, `builder.OWN_REPOS`: `packs`, and `memory` once it
is a repo, which the builder builds and `fresh`, readiness's repos row and the deck's
`K.OWN_REPOS` do not count, c-722 r1.F1). The rest is done in the deck, never by editing `config.toml` by hand
(c-618): the user clones the repos a card may name into the install, writes the rules each
space and repo's sessions read, and turns a pack on for a space of work. The first-run
stepper (c-632, "The first run" below) walks a new install through it one screen at a time;
the Setup view is the page with everything on it.

Two things are called import here, and they are different. `shipyard import <snapshot>`
([import](87-import.md)) brings an existing Keel into the install: the board and cards, the
segments, and the old config's repos listed as existing checkouts (not cloned, so outside
the layout below), its pack turned on with `packsetup.pack_space` as Turn on does.
"Import my Claude setup" (`setup.import`, below) is a card that turns the user's `~/.claude` into
a pack.

## The layout, and why it is cloned (a-84)

Onboarding CLONES a repo into the install; an existing checkout is never touched, moved or
listed by it, and a user cuts over to the clone when they want.

```
<install>/spaces/<space>/CLAUDE.md            the space tier: common rules for every repo of the space
<install>/spaces/<space>/<key>/CLAUDE.md      the repo tier: this repo's conventions
<install>/spaces/<space>/<key>/repo/          the clone (the team's committed CLAUDE.md stays inside, untouched)
<install>/spaces/<space>/<key>/trees/<card>/  each card's worktree
```

`keel/repolayout.py` owns these paths. A repo is "in the layout" only when its path is
`<install>/spaces/<space>/<key>/repo` of the loaded install config (`repolayout.spaces_of`),
so a repo a config lists anywhere else, and every repo of a config that is not an
install's, keeps everything exactly as before.

**What the tiers cover.** The tiers load, and the team-file exclude is complete, for spaces
whose worktrees Shipyard cuts (a space with no pack: `trees/` sits under the tiers). A pack
with its own `worktree` verb (ours, the work pack, cuts through its own tools) cuts outside
`trees/`, so the tiers do not load in its houses and its worktrees' team files are not
excluded; it is outside the layout until that pack cuts in it. The clone's own
`repo/**/CLAUDE.md` exclude is still added for a repo in the layout in any space, since
that path is known.

**Build output is never added** (c-734, point 13, `keel/buildout.py`). The box test's house
`git add`ed a Python suite's `__pycache__/*.pyc` and took them out in a second commit. A copy
the install made carries, in its own `info/exclude` (its common git dir, so every worktree of
it), a marked block of what is never source: `__pycache__/`, `*.py[cod]`, `.pytest_cache/`,
`.mypy_cache/`, `.ruff_cache/`, `node_modules/` and `.DS_Store`, less any the copy already
tracks paths under (review r1.F11: a repo that vendors `node_modules` keeps adding it); an
older block is replaced once and the user's own lines are kept. `git add -A` and
`git add .` then leave them out, and naming one asks for `-f`. It is written at the copy
(`reposetup`) and reconciled at every cut (`adapters.worktree`, beside the push fence), in a
space with or without a pack, so a copy made before has it too. The repo's `.gitignore` is the
team's and is never touched, and a folder the user attached is left alone. A rule in the
house's brief would be prose; a pre-commit check in the house's settings would read the
command's text, which the guards learned not to trust; git's own exclude is neither.

## The tiers, and the team's file kept out

Claude Code loads every CLAUDE.md from a session's directory upwards, so a house started in
`<key>/trees/<card>` reads the repo tier and the space tier with nothing passed at all (the
large codebases guide, https://code.claude.com/docs/en/large-codebases.md, is the pattern:
a short file per level, each holding only what is true at that level). Keel's house
contract stays above both and is not editable from Setup.

The team's own CLAUDE.md inside the clone would load too, from the worktree's root. It is
written for the team's tools and habits, may be long or stale, and is not ours to edit, so
every house on a repo in the layout runs with `claudeMdExcludes` in its settings file
(`house.settings_body`, [houses](20-houses.md)): absolute globs for
`<key>/repo/**/CLAUDE.md` and `<key>/trees/**/CLAUDE.md` (`repolayout.excludes`). The
tiers above still load; verified with real `claude -p` runs (a-84). The team's
file is read once, by the proposal card below, and what is worth keeping from it becomes
the repo tier.

`etc/claude-md/space.md` and `etc/claude-md/repo.md` are the templates a new tier starts
from: what goes in each tier, and what never does (secrets, another tier's rules, notes
about one session). Since c-678 they have the shape Bosun drafts in and Keel reads: a
repo's file has `## Prepare and test` (with a line beginning "Prepare a fresh copy:" and
one beginning "Run the tests:") and `## Running the app`, which says "Sessions run tests
only until this section says how to run the app." until the user has said how. The
`## Where work lands` section and its "Finished work lands on" line left the template in
c-734 (the line is retired, below). A tier still equal to its template reads as not
written, and so does one equal to a template it replaced, kept under
`etc/claude-md/earlier/<name>-<card>.md` (`repolayout.unwritten`: the c-678 repo and space templates, both of which lost their lands section,
so a copy nobody has drafted yet still reads not started after the upgrade); one left at the
template of before c-678 reads as written.

## What Keel does with an adopted file (c-678)

A repo's prepare command, its test command and how to run its app are not settings: they
are lines of the CLAUDE.md the user adopted, found by their opening words
(`keel/repofile.py`: "Prepare a fresh copy:", "Run the tests:" and "Run the app:", each
taking the first span in backticks; a line with none names nothing, so the template reads
as nothing). "Finished work lands on" is retired (c-734): it is read only to say that it
moves nothing (the table's row). `keel/repocommands.py` puts the others to work, for a
repo the install copied:

| Line | What Keel does with it | Where |
|---|---|---|
| Run the tests | the command a landing runs on the merged tree, and a house before review, unless the config's `[tests]` (or `[house_tests]`) names the repo, which wins | `repocommands.tests_of`; `merging.land`, `merging.trial`, `house.house_tests` |
| Prepare a fresh copy | run in a card's worktree when it is cut, and in the landing's merged tree before the tests. Through a shell, in that tree, with the environment a test suite gets, in a process group of its own, 15 minutes at most and inside the tap's budget in a landing; one that runs past its time is ended with everything it started (`merging.kill_suite`) | `adapters.prepare_fresh`, `merging.prepare_merged`, `repocommands.prepare` |
| Finished work lands on | RETIRED (c-734): nothing. Adopt and Save never check anything out. Where work lands has one source: the card's own base, else the repo's usual branch, which for a copy is the branch its remote names as its default (`refs/remotes/<remote>/HEAD`, `merging.usual_branch`), never whichever branch the copy has out. A file that still names a branch is said so in the answer ("its "Finished work lands on `staging`" line moves nothing: a card on api lands on its own base, else on main, the branch origin names as its default. To start work from staging, add it as a base on How work ships"; on a repo with an integration branch it says the card lands there and takes no base, and where the remote names no default, "the branch the copy has out", r1.F7), and on What came back. The remote's default is used only while `refs/remotes/<remote>/<name>` resolves, and fetch before work asks the remote again (`git remote set-head <remote> --auto`), so a team that changes its default is followed (r1.F4) | `onboarding.lands_named`, `repocommands.lands_said` |
| Run the app | the run rule. Until the file has it, sessions on the repo are told to run tests only and a card on it cannot take the browser ([houses](20-houses.md), "The one browser tool") | `repocommands.run_rule`, `repocommands.runs`; `Board._refuse_browser`, `house.app_block` |

**A line runs only from a file the user adopted or saved** (review F3,
`keel/tierrecord.py`). Adopt and the Setup page's Save each leave the user's note with the
file's real path and the sha256 of the text that was written (an adopted draft loses its
audit notes on the way, so the draft's own digest would not do; Save has no card, so its
note sits under the id `setup`). `repocommands.lines` hands a file's lines out only while
the file is still that text. A file edited since, by hand or by a session, and a file that
was there before this record was kept, reads as having no line at all: no prepare at the
cut, no tests in the landing or before review, no run rule. It says so in one sentence,
chosen by whether a record exists (`tierrecord.standing`: `held`, `changed`, `never`):
"<key>'s CLAUDE.md changed since it was adopted or saved, so Shipyard runs none of its lines:
adopt or save it again (Setup, the <key> repo's file).", or, for a file with no record at
all, "<key>'s CLAUDE.md has not been adopted or saved yet, so Shipyard runs none of its lines:
save it to turn them on (Setup, the <key> repo's file)." Each names the place, since a card
has no Save of its own; the drafts screen has one, Keep this text (below). It is
said as a note on the card when its worktree is cut (`adapters.say_on_card`),
in what Approve says about the landing and on the outcome gate (`repocommands.untested`),
and in the house's brief (`house.app_block`). Only the user's own note counts, so a house or
the builder cannot record one. The standing and the lines come from ONE read of the file
(`tierrecord.read`, `repocommands.reading`): the text that was checked is the text that is
parsed. A caller that holds a board passes it down (a state build, the tap, the push
worker), and the lookup has its own index (`events_tier`).

**The rule for a file that changed since its record** (review r2.F3, narrowed by the fix
check, r2.D1 and r2.D2). It is stated once, in `keel/repocommands.py`, and asked everywhere
through `repocommands.landing`, which answers the test command and the refusal from one
reading of the file:

1. The file's change turns off ITS OWN lines, and nothing else.
2. Where the config's `[tests]` names the repo's test command, that command is used exactly
   as before, at the before-review run and at the landing, whatever the file's standing.
   Nothing is refused. `[house_tests]` is used as before too.
3. A landing is refused only when the test command would have come from the file (the
   config names none) and the file's record no longer matches. Reading that as "no test
   command" would fail open: a session could edit the file and its card would merge
   untested. Keel cannot know what to test, so it lands nothing. It is asked of the
   record, whatever the file names now: a file with its test line taken out, or emptied,
   is refused too.
4. The refusal, and the brief's "do not report a pass", exist only where Keel lands the
   work itself, a space with no pack. In a space on a pack nothing about the pack's own
   flow changes.

The refusal is raised before any tree is built (`merging.test_command`, a
`merging.FileChanged`, which is a `MergeRefused`), and says what to do in order: "<key>'s
CLAUDE.md changed since it was adopted or saved, and Shipyard takes this repo's test command
from that file, so nothing was landed. First adopt or save the file again (Setup, the
<key> repo's file). Then press Unblock and land on this card." Nothing merges. The tap's
note says it first ("queued to land, and it will be refused: ..."), the card's outcome
gate says it before the tap under "will not land" (the state's
`spaces.<name>.unlandable`), the brief adds "No test run of this card counts until then:
do not report a pass." (the before-review run then has no command from the file, and one
the config names for the house is still handed to it), and a push of finished work
refuses its merge the same way.

**The pre-run is not red for it** (r2.D4). While a card's repo file stands so, the drain
spawns no pre-run for it and records `options.pretest.result = "not run"` with the
sentence, once per pair of heads (`landing.pre_run_one`); the card's chip reads "not
pre-run". A Save moves neither head, so a "not run" is run as soon as the file's record
matches again. A queued Approve that is refused this way blocks the card, and its stuck
line (`land-file`, `keel/stuckcards.py`) has the fix in two steps: while the file stands
changed, **Open the file to save it** opens Set up your repos with Bosun, whose row has
Keep this text; once the record matches, **Unblock and land** sends the deck's own
`unblock` of that block (`expect` names it, so no other block is lifted), then Approve.

**Every fix that lands a refused card sends the same steps, from one helper**
(`stuckcards.lands`): its own verb where it has one (`land.aside`, `land.unlock`), then
`unblock` with `expect` set to that block, then Approve, each only when the server took
the one before (`follow` in `app/ui.stuckcard.js`, `then: "land"`). Approve is sent only
when the card the unblock answers with is no longer blocked. The server does not refuse an
unblock whose `expect` no longer matches, it answers with the card as it is
(`Board.unblock`), so a card that comes back still blocked is blocked on something else:
nothing more is sent and the page says "<card> is blocked on something else now, so it was
not approved. Read the block on the card." A bare Approve after
the verb is refused on a blocked card where landings are queued (`[keel] merge_queue`),
which is what the lock fix and Set them aside and land sent before.

"Lands untested" is left for a file with no record at all and for a held file that
names no test line.

The deny rules are not the mechanism, the refusal is. `house.tier_deny` puts the four
editing tools on the CLAUDE.md of EVERY space and of each repo the install copied into
one, and a Bash rule on a command that spells one of those absolute paths (built as
`secret_deny` builds its own, never on the bare file name, since every repo has a CLAUDE.md
that is the house's ordinary work). They stop the plain attempt only: a shell can spell a
path another way and a program it runs can open the file, and then the file is no longer
the recorded text, runs nothing and lands nothing. The template
written when a repo is copied records nothing: it names no command. **On an existing
install** this means a copied repo's file runs nothing until it is adopted or saved once
after the upgrade; a repo with `[tests]` in the config keeps its config command.

- **A prepare that fails** refuses the cut ("could not prepare a fresh copy of <key>: ...",
  with the command's last lines), and the worktree is taken back out while its branch
  stays, so the next try cuts and prepares again. A worktree that is already there is
  never prepared again. In a landing it lands nothing.
- **A repo with no test command lands untested.** Approve's note says so and why, and so
  does the card's outcome gate before the tap ([cards and gates](10-cards-and-gates.md)).
  A repo whose file changed since it was adopted or saved does not land at all (above).
- **Lands on, retired (c-734).** Until c-734 an Adopt or a Save switched Keel's copy to the
  branch the line named (`apply_lands`, c-678), and a card naming no base landed on the
  branch the copy had out (c-732). That was two sources for one answer: on the second
  stranger run the user answered "staging" to Bosun's question, the adopted file said so,
  the copy was switched to staging, and every card naming no base would have landed there
  while Bosun's next plan read staging as the repo's usual branch. Nothing in the answer's
  options said that it moved the copy. Now the copy's checkout is never moved by a file and
  never decides where a card lands; a card is cut from and lands on its own base, else its
  usual branch (`merging.usual_branch`: the remote's default for a copy, read the same way by
  the cut, `adapters.start_point`, the landing, `merging.landing_target`, a house's target,
  `house.target_of`, fetch before work, and the page, `landpush.panel` and the suggested
  base on How work ships). A checkout of the user's own (Use a folder I already have) keeps
  the branch it has out, and a repo with an integration branch keeps landing there and takes
  no base (c-732 r1.F4). The cut records the usual branch it cut from on the card
  (`options.cut_from`, by repo key, `adapters.cut_point`), and the landing and the house's
  target prefer it to the usual branch read again (`merging.cut_from`, r2.F1): a team that
  moves its default after the cut (the next card's fetch before work follows it) never has
  this card land on the new default carrying the old one's history. Its order is the
  integration branch, the card's own base, the branch it was cut from, then the usual branch.
  Only the drain writes `options.cut_from` (a re-cut overwrites that repo's entry, r2.D3),
  and a name in it that is not a branch name is not read (r2.D1,
  [cards and gates](10-cards-and-gates.md)).

What came back shows these lines beside each draft, with the line of the file each came
from, before they do anything: they take effect at Adopt and not before.

## What of the first run reaches an install that was already set up (c-678 review)

The first-run work is screens and titles, with these exceptions. Each is said here so an
upgrade holds no surprise; each reaches only a repo the install copied into its own layout
(`<install>/spaces/<space>/<key>/repo`), so an install whose repos are attached where they
were sees only the last one.

| Change | Reaches an existing install? |
|---|---|
| Fetch before work, and Push after a landing | No. Both switches default off; only a space made while the first run is not finished has them written on (`reposetup.add_space` reads `firstrun.json`'s `finished`). A space added from Setup on a finished install gets neither, and a config that names neither is unchanged |
| Lines run from a repo's CLAUDE.md (prepare, tests, lands on, run) | No file runs anything until it is adopted or saved once after the upgrade ("A line runs only from a file the user adopted or saved", above). `[tests]` in the config is unchanged |
| A card cannot take the browser on a copied repo whose file has no "Run the app" line (`Board._refuse_browser`) | Yes, by design (step 11): on such a repo a new card with `options.browser`, or a set of it, is refused until the file says how to run the app |
| The sign-in banner's wording | Yes: "Shipyard's Claude sign-in ran out, so no session can run", naming the space where another space has a sign-in of its own |
| The builder's limits in auto mode: the hard deny on installing software, changing settings and writing outside its clones and card folders, and every copied repo counted as a live checkout its guard refuses writes in (`builder.live_repos`) | Yes, for an auto-mode builder; a bypass-mode builder gets the wider guard only. The builder never writes in the user's copied repos |

## Worktrees

A personal card on a repo in the layout cuts its worktree at `<key>/trees/<card>`
(`adapters.worktree_dirs`), and everything that finds a personal worktree again asks
`repolayout.card_tree`: the merge and its clean up, Drop in, the review gate. A pack's own
`worktree` verb is unchanged. `plangate` treats a path under `trees/` as a worktree, so a
plan file there is refused like one under `state/worktrees/`.

## The Setup view

`?view=setup`, drawn by `app/ui.setup.js` from `GET /api/setup` (`onboarding.report`). On
the desk it is on the rail; on the phone it is under More, not in the dock. It no longer
opens itself on a fresh install: the first-run stepper does that (below), and draws its
screens from the same parts, which `ui.setup.js` exports as `K.setupParts`.

- **Per space**: its tier in a textarea with Save; its repos, each with its path (`missing`
  when the path holds no `.git`, `existing checkout` when it is not a clone of this
  install) and Remove; for a cloned repo, its tier with Save, and Propose from the repo
  (with its "What do you like?" box) or the open proposal with Adopt; the same Propose for
  the space tier once a repo is cloned; a Clone form of a key and a URL; and an Attach form
  of a key and the path of a checkout the user already has (c-632), listed where it is.
- **Packs**: on an install, the one line for a pack someone shared (c-740, [packs](62-packs.md),
  "A pack someone shared": `git clone <its address> <install>/packs/<name>` with the
  install's own folder filled in, a Copy, then Look again), and a problem line each for what
  is wrong in the packs folder (`packProblems`: a folder that is not called what its pack is
  stands beside the packs that still list). A pack with a repo of its own says so on its
  row, with "Let Bosun build this pack" until Bosun builds it there (r1.F1,
  `setup.pack.build`). Then
  every pack the roots hold, its description, its
  `[[requires]]` checks run on this machine, the spaces already on it, each with its Turn
  off (c-688, `setup.pack.off`: the pack and what Turn on wrote for it come off and the
  space stays; refused while the space has open cards), and Turn on, offered only for a
  space the pack is not on (c-734): "Turn on for <space>" for each space with no pack, and
  "Turn on for a new space", which asks its name. A pack on for its only space showed both
  a bare Turn on and Turn off for that space on the second stranger run, which read as if
  it were off. A pack that says `demo_only` (the sandbox) is not listed on an install unless
  a space is already on it (c-688, [packs](62-packs.md)). Until c-677 the second pack's button was handed its place in the list as
  the space: it read "Turn on for 1" and its tap threw, so nothing was sent. A check
  that passes is a badge; one that fails is the stuck line ("A requirement that needs
  you", below), where it used to be a red badge whose reason was a hover title. A pack on
  for no space draws its failing checks as one quiet line instead, "needs: GitHub sign-in"
  (c-734, as an unchosen option does on Where finished work goes): nobody has chosen it, so
  nothing needs the user yet.
- **Your own Claude** (on an install with a builder): Import my Claude setup
  (`setup.import`, below).

The report is fetched when a page that draws it opens, after each change and on Look again,
never on the deck's poll: it runs every pack's checks, and drops readiness's kept readings
(`readiness.forget`) so the next state agrees with it. After a change the page reads the
answer's `restarting` (set by the server for `onboarding.CONFIG_VERBS`) to know whether the
deck is re-executing, rather than guessing from the verb's name.

**The page never blanks** (c-729). On the stranger run every setup tap blanked the step
("reading the setup...") and brought it back, and Done and Next stayed stale until a reload.
Three things changed:

- **The deck reads most config changes in place** (`keel/deckreload.py`). A config verb's
  answer carries `reloaded: true` and nothing restarts: the handler's `cfg` and the deck's
  are swapped for the file as saved (`Deck.reread` drops the documents and the kept
  readings). It still re-execs (`restarting: true`) for a change to what the process bound
  at start, `deckreload.BOUND` and every `voice_` field (its port, its state, voice, whose
  gateway is reinstalled first), and for a config that does not load. A verb that wrote the
  config and then failed is followed the same way, before its refusal is answered
  (`serve.config_stamp`, r1.F5), its restart reinstalling the voice gateway first when the
  file now differs in a voice field (`deckreload.voice_moved`, r2.F6), so the running deck
  never holds a config the file no
  longer says; recording the bypass acceptance after a builder save is best effort, and a
  Claude folder it cannot write is said in the save's `note` (`settings.bypass_after`). Measured on the
  first run, every tap was a restart before: Choose your builder, Add repo, Use a folder,
  Remove, the plan question, Turn on (a pack), Back up's Turn on. Now none is, unless it
  changes voice.
- **The page keeps what it shows** (`app/ui.setup.js`, `change`). The report is never
  dropped while a change runs: the row the user pressed in (the nearest `data-key` around
  the click) is dimmed and marked "working" (`K.markWorking`, after every paint), the new
  report is asked for at once, or, after a restart, until a process with a new `boot` (on
  `/api/setup`, `serve.BOOT`) answers, and then the state is read again so Done, the list's
  marks and Next follow; only then does the mark go. Look again keeps the screen the same way.
  A read asked for while another is on its way is kept, never dropped: it goes once that
  one lands, with every caller's next step (`load`, r1.F3), since the earlier read may
  predate the change.
- **A reopened event stream reads the state** (`app/ui.core.js`, `openStream`): a stream
  starts at what its deck holds now, so after a restart nothing said `state` until the next
  write. Every open after a page's first reads the state once.

## The first run

A new install opens on Start, `?view=start&step=<id>` (`app/ui.start.js`, c-632), one step
per screen. Sign in to Claude says in its own paragraph that this is a NEW setup with its
own Claude sign-in in `<install>/claude`, and that the user's own `~/.claude` is not read
or changed; Meet Bosun carries the way to bring anything over from it (Import my Claude
setup, a quiet link there). Until c-678 a note on three steps said both.

### The step order (c-677)

The order is the one approved in the first-run design (c-668): thirteen places, 0 to 12.
`keel/firstrun.py` holds the steps (`STEPS`, in order), and it is the ONE place that names
them. This table is every place.

| # | Place | Step id | Today |
|---|---|---|---|
| 0 | Choose your builder | `choose-builder` (no Skip) | in: the two forms as option cards, neither preselected (c-678) |
| 1 | Check this computer | `prerequisites` (required) | in: the machine's checks, the first half of the old Prerequisites step |
| 2 | Sign in to Claude | `login` (required) | in: the install's login, its second half |
| 3 | Meet Bosun | `builder` | in: the three checks, how to open Bosun's session, the hello check, and the import (c-678) |
| 4 | Add your repos | `repos` | in: the space named once, a panel per repo, Add another repo, a failed copy sorted into its kind (c-678) |
| 5 | How Keel remembers | `memory` (no Skip) | in: the read-only picture of the four layers (c-678) |
| 6 | Set up your repos with Bosun | `rules` | in: the hand-over to Bosun, what it will ask, and what came back to read and Adopt (c-678) |
| 7 | Where finished work goes | `integrations` | in: per space, a connection to its code host or the merge on this computer with a Push (c-678), the GitHub connection where it is offered, and another provider drafted with Bosun |
| 8 | How work ships | `defaults` | in: where work starts (the space's bases), the rest asked by Bosun, the flow drawn as places and arrows with Bosun's draft to Adopt, and the plan question (c-678, c-732) |
| 9 | A browser for sessions (optional) | `browser` (optional) | in: Node's check and the one download with its progress, the downloader's own count (c-678, c-757) |
| 10 | Back up | `backup` | in: a folder as the store, the three checks as they are observed, and the passphrase shown once (c-678, c-757) |
| 11 | Your first card | `first-card` | in: the form, the card Bosun suggested, and the card's path past review to landed (c-678) |
| 12 | You are set up | `set-up` (no Skip) | in: where to go when something does not work, what was set, what was skipped, and the phone and voice under More to set up later (c-678) |

Step ids did not change where a step kept its content, so a stored skip, a needs panel's
link and a pack's `after` still find their step. Two ids are gone. `spaces`: a stored skip
of it is left in `firstrun.json` and read by nothing, and a pack that names it is placed
after `repos` (`packs.SETUP_MOVED`). `phone` (c-678): Phone and voice is no step, it is on
the last screen under "More to set up later"; a stored skip of it is read by nothing, a
pack that names it is placed after `first-card` (so no pack's step follows the last
screen), and the `phone` readiness row points at `set-up` (`readiness.STEPS`), which is where
a needs panel's Set it up now lands. The `voice` row points at no step (c-729, the owner's
call: no voice step is built): the stranger run's "Set up voice" on Now opened a Start that
had none. Its needs panel says "Ask Bosun how to set up voice on this computer." with Open
Bosun (`/console`) and Bosun's attach command with Copy while its session can run
(`ASK_BOSUN` in `app/ui.core.js`, the same way in as the first run's "Stuck? Open Bosun's
session" line). The other rows Now and the pages' needs panels draw on a fresh install
(`prerequisites`, `builder`, `repos`, `rules`, the integration rows, `browser`, `backup`,
`phone`) each name a step that sets them up.

**Adding a step** is three entries and nothing else:

1. a `Step(id, title, about, required=..., optional=..., headline=..., skip=...)` in
   `firstrun.STEPS`, at its place (`headline` heads the screen where the design gives more
   than the list's title; `skip=False` is a step with no Skip that Finish does not wait for);
2. how it reads as done, in `firstrunsteps.STATE`: `"<id>": fn`, where `fn(cfg, ready, board)`
   returns `(done, why)` or `(done, why, extra)`. `done` is read each time, never stored;
   `None` means there is nothing to check. `extra` goes onto the step's entry in the report;
3. its screen, in the deck: `K.startPanels['<id>'] = function (report, step) { ... }`
   in `app/ui.start.js`, returning nodes. A screen of any size is its own file, listed in
   `app/views.json` before `ui.start.js`, which reads what it exports onto `K` (`own`); the
   file is then added to `SCREENS` in `tests/test_start_steps.py` and to the module list in
   `tests/fixtures/start-page.js`.

`packs.SETUP_AFTER` must list the same ids (a test holds them equal), and a readiness row
that the step sets up names it in `readiness.STEPS`.

Check this computer and Sign in to Claude are the required steps; every other may be
skipped (but Choose your builder, which has no Skip and waits for the pick, without being
a step Finish waits for), and a skipped step is not lost: it stays on the list, and the page that needs it
shows its needs panel ([the deck](40-deck.md), c-631), whose Set it up opens the step again.

| Step | Done when | The screen |
|---|---|---|
| `choose-builder` | builder mode is on and the config's `[builder]` names a `mode` (`firstrunsteps.chosen`); its why is the form, "Full builder" or "Guide builder", and the step carries `choice` (`full`, `guide` or null). No Skip, and not required: Finish and the redirect never wait for it | the two option cards ("Choose your builder and Meet Bosun", below) |
| `prerequisites` (required) | readiness `prerequisites` is ready | each check of `prereqs.gather` by its label; one that fails is the stuck line with the three parts the check carries ("Check this computer", below); git's name and email as two fields and Save; Check again (the report read again); and the line "Your builder joins two steps from now. Until then each row carries its own fix." |
| `login` (required) | readiness `login` is ready, and its why is that row's own sentence. A login that could not be checked last time is ready (houses try it as they run, as the drain does), so Next and Finish are on, and the row and the step carry `sure: false`: it is said as not confirmed, with no "Done", no done colour and the list word `not checked` | the guided sign-in ("Sign in to Claude", below): four lines with the one command, the live status read from that same row, so the list and the screen cannot disagree, and Check again (`firstrun.login.check`) |
| `builder` | readiness `builder` is ready (builder mode is on and Start would not refuse, `console.start_refusal`: a config dir another Unix user owns, then `builder.refusal`), Bosun's session is up (`console.view`), and the user has said something in it (`keel/bosunhello.py`); the step carries `running` and `hello` | the form chosen, three checks, Open Bosun's session, the hello check, and Import my Claude setup as a quiet link (below) |
| `repos` | any space's `repos` row is ready (c-678: the user's repos go in a space of their own, so personal, which holds only the install's packs, waits for none); its why is those rows' sentences | the space name, a panel per repo, Add another repo and Use a folder I already have ("Add your repos", below) |
| `memory` | never: nothing to check, so it is not counted and its Next is always on. No Skip: it is read only | the four layers, top to bottom ("How Shipyard remembers", below) |
| `rules` | every repo the install copied has its CLAUDE.md adopted (`tierdrafts.verdict`: the tier is no longer its template and no proposal is open on it; the workspace file is not required); the step carries `drafts`, the light rows | the three parts ("Set up your repos with Bosun", below); a pack's rules listed as already read by its sessions (decision `pack-rules`: list) |
| `integrations` | for each space on a pack, its `codehost` row is ready, and its `tracker`, `ci` and `reviews` rows where the space declares them (`readiness.wanted`: `ci` is optional, so the sandbox finishes; `reviews` and `tracker` too since c-730, so a space that has not asked for review requests, or whose pack is a code host alone as the GitHub pack is, is not held). A space with no pack ships by the merge on this computer and the Push, which needs nothing set up: with no pack anywhere the step has nothing to check and is not counted (`firstrunsteps.integrations_state`). A connection Bosun is drafting, or one it drafted that is not turned on, for a space on none, is not done and says so (c-758, `draft_waiting`) | the options per space ("Where finished work goes", below) |
| a pack's own (`<pack>:<id>`) | its named checks pass and its capabilities are ready ([packs](62-packs.md), `[[setup]]`) | its text and its checks, after the step its `after` names |
| `defaults` | never: nothing to check, and it is not counted; the step carries `plans`, whether a new card of each space stops at its plan (`firstrunsteps.ships_state`) | the path a finished card takes, per space ("How work ships", below) |
| `browser` (optional) | Shipyard's browser is in its folder (`firstrunsteps.browser_state`, `browserinstall.status`); the step carries `node` and `install`, the download as it stands | the two checks ("A browser for sessions", below) |
| `backup` | backup is on and a copy of this install's has been written (`firstrunsteps.backup_state`, `backupstatus.verdict`, c-757), and it never goes back to not done. With no copy yet: done for Next and not confirmed (`sure: false`, `word` "copy pending") while one is being written or still to come, and not done once the first run failed or never started. With a copy: done and not confirmed, with its own `word`, when the folder cannot be written ("folder missing"), else a run failed after the copy ("last run failed"), else the proof failed ("proof failed"). The step carries `backup`, the store and what is observed of it (`backupstatus.status`) | the folder and Turn on backup, then the checks ("Back up", below) |
| `first-card` | a card the user filed (not a proposal or a draft card, a tier's or a flow's, and not the import or a connection draft) has reached review or later; the step carries `card` (its id, title, stage and the block a refused landing left) and, while no card is filed, `suggestion`. The Push a local landing offers reads the repo, so it is not on the state: it comes with the card's own detail, which the screen asks for once the card has landed | the form, then the card's path ("Your first card", below) |
| `set-up` | never: nothing to check, and it is not counted. No Skip | the last screen ("You are set up", below) |

**Done is never stored.** It is read each time from readiness, the config or the board, so a
thing fixed by hand marks its step done too. `state/firstrun.json` holds only
`{"skipped": {step: at}, "finished": at | null}`, and `seen` (below), written with `atomicfile`, each read, change
and write as one step under a lock (`firstrun.change`), the first write from a state read
included, so a Skip at that moment is never lost. On an install
with no file it is written on the first read: as finished, with `reason: "existing
install"`, when a space already lists a repo (`onboarding.fresh` is false), so a deck set up
before the stepper is never sent to Start; else as not finished. A config that is not an
install's never redirects and writes nothing.

**A step with nothing to check, once the user has been through it** (c-729). How Shipyard
remembers, How work ships, and Where finished work goes while its default (B) stands read
`done: null`, so the list never marked them, however often the user went past. Going on
past one (Next, or Keep how it works now on How work ships) sends `firstrun.seen` on the way (quietly,
`goPast` in `app/ui.start.js`), which records `seen: {step: at}`; from then on the step
reads done, with `firstrun.SEEN`'s sentence ("you have read how Shipyard remembers", "you
kept the usual path", or the local landing's), and carries `seen`, which turns Keep how it works now
into **Kept**. A step with a check of its own is refused.

**An install that is already set up** (c-677). The new order asks it nothing: its
`firstrun.json` is read as it is and not rewritten, the two required steps are the two
halves of the one it already met, so `redirect` is true under exactly the conditions it was,
and no step runs, resets or re-asks anything by being drawn. Its Next is the one it had: off
only on a required step that is not done, with no hint to finish or skip, so paging through
steps it left open sends and writes nothing. Start is reached from More there, and Setup
from the rail.

**An install nobody has acted on** (c-677). Until c-678 Choose your builder read done on a
fresh install, because builder mode ships on, so resuming at the first open step would pass
it unseen (it is open now until the pick, and an install made before c-678, whose config
names a mode, still reads done there). The report says `untouched` while `firstrun.json` holds no skip and no Finish AND no
step after Meet Bosun is done (a repo, a tier, a pack, a card, a backup: each is the user's
doing; a builder that is on and checks that pass are what `shipyard init` leaves). It is
read each time and never stored. While it is true, Start opens on the first step; a skip, a
Finish or the first repo ends it, and the resume is the usual one. What is chosen on step 0
does not end it: a builder mode saved there leaves the screen on that step. Signing in does
not end it either. Step 0 returns only when the deck is
opened with no `?step=` in the address (the bare deck, More, a home-screen icon): a reload
of a step's own address stays on that step. The cost is a few taps on Next, and it cannot
outlast Add your repos, where Next waits for a repo or a skip and either ends it.

**The state.** `/api/state` carries `firstrun` (`firstrun.report`): `install`, `finished`,
`reason`, `redirect`, `untouched`, and each step's `id`, `title`, `headline`, `about`, `required`, `optional`, `bosun`
(true from Meet Bosun on, a pack's step included), `done` (None for How work ships),
`skipped`, `why`, for Sign in to Claude `seen` and `stamp` (its sign-in file), and for Your
first card the `card` it follows; and `watch` (c-734, `firstrun.watch`), the stamp of the
setup cards that has the page read the Setup report again ("The page follows the board",
under Where finished work goes). `/api/setup` carries `start`
(`firstrun.panels`): the machine's checks with their fixes, the login, the phone's command,
and each pack step's text. The state is the one source of a step's state; the deck stores
nothing of it.

**The deck.** A deck loaded with no `?view=` opens Start while `redirect` is true: until
Finish, and whenever a required step stops being met after it. It replaces the history
entry, so Back does not loop. It resumes at `?step=`, else at the first step neither done
nor skipped (the first step of all while `untouched`); a step with nothing to check counts
as not done until the user has been through it (`seen`, above), so a resume never passes
one unseen. The step it resumed at is then kept by the page (`App.step`, c-734), so the
state after an action on it does not resume again further on. On the second stranger run
the page had resumed at Set up your repos with Bosun; its Adopt marked the step done, and
the next state resumed past Where finished work goes and How work ships to A browser for
sessions. Start is on the desk's rail until Finish and under More always.
`K.openStep(id, space)` is the one way to a step, and `K.stepHref` builds its link.

- **The list.** On the desk the steps are listed on the left, each with its place (counted
  from 0, as the design numbers them), its title, `required` or `optional` under it, and its
  state in a word: `here` for the one on screen, else `done` or `skipped` (for a step
  that is done and not confirmed, `sure: false`, the step's own `word` where it carries
  one, Back up's "copy pending", else `not checked`), else nothing. The
  list's head says "N of M", the step's place and the last one's. On the phone the same
  counter and the step's title sit on a strip with one mark per step, and the list opens
  under Steps.
- **The screen.** The step's title, what it is for, its done or skipped line, its panel,
  and at the foot Back, Skip (Unskip on a skipped step; neither on a required step), Next
  and Finish. **Next is the step's own state**: on once the step is done, skipped, or has
  nothing to check, and off otherwise, with "Finish this step to go on, or Skip." beside
  it (without "or Skip" on a required step). Until c-677 Next was off only on a required
  step, and on an install whose first run is finished it still is, with no hint. The list
  still opens any step, and Finish is on once the required steps are done.
- **The header line.** From Meet Bosun on (`step.bosun`) the page is headed by one line:
  "Stuck? Open Bosun's session", the attach command and Copy (`K.bosunLine`,
  `app/ui.stuck.js`). It is not drawn while Bosun's session cannot run (below).

### A requirement that needs you (c-677)

One component, the stuck line (`K.stuck`, `app/ui.stuck.js`), draws every requirement that
needs the user, in Setup and on every step. It has up to three parts:

1. **What happened**: the reason the report already carries (a readiness row's `why`, a
   machine check's `what`), in its own words: a closing full stop is added and its case is
   never changed, since it may begin with a tool's own name. A name in backticks is drawn
   as code (c-678), as in a fix. A pack's check carries why the
   pack needs it, so it is said as readiness says it: "<name> is not set up: <why>".
2. **The fix**, when the report has one: the login's command, a form where the page itself
   can do the fix (git's name and email), and a check's own, drawn by `K.fixOf`, the ONE
   renderer of a fix sentence and its command: the `fix` sentence, the `command` with Copy,
   and `done_when`, how the user knows it worked. A pack's check brings them as the pack
   wrote them in `[[requires]]` (c-688, [packs](62-packs.md)); a machine check brings its
   `fix` and `command` from `keel/prereqs.py` (c-679, the same keys, and no `done_when`
   yet). A readiness row that a failing check holds up carries those checks as `needs` and
   draws the same. A check or a row with no fix leaves the part out. Nothing in the deck
   invents a fix.
3. **"or ask Bosun in its session:"** with the attach command and Copy, whenever Bosun's
   session can run (below), on any step, the ones before Meet Bosun included. Only the
   header line waits for Meet Bosun.

A requirement that does not block is drawn in the line's quiet form (`quiet`): the same
parts, a muted mark, and no "needs you". Two things use it: a machine check that fails and
is not required (its step still reads done), and a login that could not be checked.

### The stuck states outside setup (c-678)

The same line says what is stuck after setup too. `keel/stuckcards.py` holds the readings
and the fixes; `app/ui.stuckcard.js` draws them.

**A blocked card Keel can read.** A block is a line Keel wrote for itself.
`stuckcards.read(cfg, card)` turns it into what happened and its fix, each time and never
stored; the state carries it as `stuck` on a blocked card, and the pane draws it above the
block's own words (`K.stuckCard`, in `gateEvidence`). A block that is not one of these (a
session's question) is left as it is.

| kind | The block | What happened | The fix |
|---|---|---|---|
| `no-model` | "no model on ..." | "No session started for c-9: this card names no model, and Shipyard never guesses one." | **Use opus (this space's default) and start**: `stuck.model` sets the space's default, then the card's fresh start (`house.retry`) |
| `start-failed` | "house failed to start: ..." | "No session started for c-9: <the reason>." | **Try again** (`house.retry`) |
| `land-tests` | a refused landing whose tests were red | "The merged result failed `npm test`: 2 failed. Nothing landed." (the command and the count are read from the refusal) | **Send back with the failures** (`sendback`, the refusal as the reason) |
| `land-dirty` | "<repo> has uncommitted changes on <branch>" | "The folder Shipyard lands into has changes that were never committed: README.md, package.json. Shipyard will not merge over them." (the files are read from git now) | Keel's own copy: **Set them aside and land** (`land.aside`: a named stash there, then `unblock` of that block, then Approve again). A folder the user attached: the two commands to copy, `git -C <folder> stash push` and `stash pop`, and no button |
| `land-file` | the repo's CLAUDE.md changed since it was adopted or saved, and the test command comes from it | "Nothing landed: <key>'s CLAUDE.md changed since it was adopted or saved, and Shipyard takes this repo's test command from that file." | while the file stands changed: **Open the file to save it** (the step). Once it is saved: **Unblock and land** (`unblock` of that block, then Approve) |
| `land-lock` | git's `index.lock` left behind | "The merge did not go through: a git lock file was left behind in the folder Shipyard lands into." | Keel's own copy: **Remove the stale lock and land** (`land.unlock`, then `unblock` of that block, then Approve again, which the label says; a refused step is followed by nothing). The user's folder: the `rm` to copy |
| `land-identity` | git has no name and email | "The merge did not go through: git does not know your name and email, which every merge records." | **Set your name and email**, which opens Check this computer |
| `land-other` | anything else git said | "The merge did not go through: <git's line>." | none |

A landing that conflicts is not here: it never blocks, the card goes back to its session
to merge ([cards and gates](10-cards-and-gates.md)).

**The services.** On an install, when the drain has stopped and is not paused on purpose
(`drain.alive` false on the state), Now says "The part of Shipyard that starts sessions and
lands work has stopped." with **Restart it** (`K.servicesStuck`; `services.restart`,
`stuckcards.restart_services`, which asks the service manager itself: `manager.restart` of
the drain's label when it is loaded, `manager.start` when its file is installed and it is
not; refused when the service is not installed, or when another install's drain runs).

**An unknown key in the config.** The loader's unknown-key warnings are read into
`config.unknown` on the state (`stuckcards.unknown_keys`), and each is a quiet stuck line
on Now and in Settings (`K.unknownKeys`): "config.toml has a setting Shipyard does not know:
`[keel] huose_max`. It was ignored and the default is in use.", with **Rename to
houses_max** where Keel knows a near name (`setup.config.rename`) and **Remove this line**
(`setup.config.remove`). Both are config verbs, written through `setupconfig.edit` (checked,
backed up, the deck re-execs); a key Keel knows is refused by both, and a rename whose
value the setting may not take changes nothing. The warning panel keeps the warnings that
are not unknown keys.

**The sign-in that ran out.** The banner (`loginBanner`, `app/ui.views.js`) says, for the
install's own sign-in, "Shipyard's Claude sign-in ran out, so no session can run" (where
another space signs in with a folder of its own, "so no session of the personal space can
run": `login.public`'s `only`, `readiness.RAN_OUT_SPACE`), then "They pick up
where they stopped once you sign in.", with the guided sign-in under Sign in again
("Sign in to Claude", below) and a third part of its own: "or ask Bosun in its session (it
is paused until you sign in):" with the command. `K.bosunSession` draws none there, since
nothing can answer; this line says why. Another space's login keeps its own words.

**Where the design and the code differ.**
- **A branch rewritten outside Keel has no button.** The design gives "Bring the working
  copy in line (keeps the backup branch)". Keel moves no branch there, by a recorded
  decision ([cards and gates](10-cards-and-gates.md), "A pull request's branch rewritten
  OUTSIDE Keel": a tap that did was built and taken out). The card still says what is so
  and gives the command to copy, as before.
- **"It runs out on Thursday", two days before**, is not said: Keel learns that a sign-in
  ran out from a session that failed, and holds no date for when one will.
- **A session waiting for a slot** ("all 3 session slots are busy, yours is next") is not a
  block, so it is not a stuck line; the card already says it waits.
- A start that failed because the sign-in ran out reads as any failed start, with Try
  again; the banner above it is what says to sign in.
- The landing sentences name what the refusal names: the command and how many failed are
  read out of the board's block, and a refusal that names no test says "some failed".

### Sign in to Claude (c-678)

The step's screen is the first-run design's step 2, and it is ONE block,
`K.signIn.block` (`app/ui.signin.js`), that three places draw: this step, the sign-in
banner on Now and Attention, and a red Claude row of the Logins list
([the deck](40-deck.md)). The last two fold it under **Sign in again** (`K.signIn.again`).

- **The four lines.** Open a terminal; paste the one command, with Copy, and press Return;
  the browser opens (or the terminal prints a link); come back, with nothing to press. The
  command is the server's, `login.signin_command`: `claude auth login` under the space's own
  Claude folder, the same line the Logins list copies (`loginprobe.claude_fix`). The step
  reads it as `start.login.command` on `/api/setup`, the banner as the space's
  `login.signin` on the state. Nothing in the page types into a terminal, and there is no
  field for a token or a password.
- **The live status**, one row, "Claude sign-in for this install", in four states
  (`K.signIn.status`): waiting ("Waiting for you to sign in."), checking ("Sign-in seen.
  Making sure it works."), ready ("Signed in. Shipyard can run sessions."), and could not tell
  ("Shipyard could not reach Claude to check (<the probe's reason>). Check your connection,
  then press Check again."). The design draws the last as "needs you". Here it is the stuck
  line's quiet form with Check again as its fix, because a login that could not be checked
  does not block: houses try it as they run, Next and Finish are on, and it is never said
  as working (the rule above, c-677).
- **Watch the file, then one probe.** The step's entry on the state carries `seen` and
  `stamp`: whether the sign-in file is in the install's Claude folder and when it last
  changed (`login.signin_stamp`: the credentials file, or on a Mac the account file once it
  names an account). It is one file's `stat`, read on every state. When the block is drawn
  with a stamp it has not asked about and no good answer, it sends `firstrun.login.check`
  itself: once per stamp, so a redraw or a probe that says "not signed in" never asks
  again, and a sign-in made after that is asked about once more. A probe that could not
  tell is not repeated by the page. The probe is never made from the state build: it can
  take 45 seconds, and the state is built on every poll.
- **Under it**: Common problems, folded ("command not found: claude": go Back; "I signed in
  but this page still waits": Check again), and "Next you meet your builder. It needs this
  sign-in to run."

The step's headline is "Sign Shipyard in to Claude" (`Step.headline`: what heads a screen where
the design gives more than the list's title), and its paragraph says what the old "This is
a new setup" note said: Keel keeps its own sign-in in its own folder, and nothing here
reads or changes the Claude setup the user already has.

Readiness's `login` row no longer names a command (it used to end with `login.fix_command`,
a different line from the one this screen shows): it says "Shipyard is not signed in to Claude
yet", or "Shipyard's Claude sign-in ran out, so no session can run" for a folder that held a
sign-in once ([packs](62-packs.md), the readiness rows).

**Not proven here.** The first-run plan asks that the sign-in command be proven on a clean
user account before this step is trusted. `claude auth login` exists in the installed
Claude Code (2.1.292) and the Logins list has copied this same line since c-558, but this
card ran no sign-in on a fresh account: that walk is still owed.

### Choose your builder and Meet Bosun (c-678)

Both screens are `app/ui.startbosun.js` (`K.builderChoice`, `K.meetBosun`), the first-run
design's steps 0 and 3.

**Choose your builder.** Two option cards, Full and Guide, each with the design's five
lines (in one line, what you gain, what you do by hand, what it can build, what to know),
then "Not sure? Start with Guide. You can switch in Settings." and What is a builder,
folded. Neither card is preselected (decision `preselect`), and the way on reads Continue
and waits for a pick ("Pick a builder to continue."). A pick sends ONE
`setup.settings.save`: builder mode on, and `[builder] mode` as the form names it (Full is
`bypass`, Guide is `auto`; [Bosun](96-bosun.md)). A pick the server refused is said in a
panel, "Your choice was not saved.", with why (another setup change still running, or the
server's own sentence) and Try again, which sends the same pick.

Whether a form is chosen is read from the config and never stored: the config's `[builder]`
names a `mode`. So a new install must name none (`etc/shipyard.example.toml` carries the
line commented out), and an install made before c-678 reads as having chosen what its file
says. The step has no Skip, as the design draws it, and is NOT one of the required steps:
making it required would send a finished install with no `mode` line back to Start.

**Meet Bosun.** One line saying the form chosen, with Change (back to step 0), then:

| Row | Ready when | Otherwise |
|---|---|---|
| Builder is switched on | `start.bosun.on` (`builder.status`) | needs you: Choose your builder |
| Bosun's workspace is ready | `start.bosun.workspace`: Start would not refuse (`console.start_refusal`, a clone Start makes first counted as there) | needs you, in Start's own sentence, or the design's for a missing clone |
| Bosun is running | the state's `console.up` (the harness lists its session) | needs you: Start Bosun, the existing `console.start` tap; "Starting (a few seconds)" while it runs; after a start that was refused, "Bosun could not start: <why>" with Start again and Copy details |
| You said hello in Bosun's session | the step's `hello` | waiting: "Start Bosun first", or "Waiting for your first message" |

Between the last two is the panel that teaches the one thing the rest of setup needs,
**Open Bosun's session**: the attach command with Copy, "Or open Bosun in the Claude app: it
is the session named Bosun.", and "Say hello there. Then come back to this page." The page
draws no conversation and starts none. The row for a Bosun that is not running has no "or
ask Bosun" part (`K.stuck`'s `ask: false`), since Bosun is the thing that is down.

**The hello check** (`keel/bosunhello.py`). `said(cfg)` is true once a transcript of a
session Bosun has had holds a user message that is the user's own: the session
`state/console.json` names now, then the ones its history names, so a hello survives a
Restart. Not the user's: what Keel typed to start or resume it (`console.START_PROMPT`,
"You are Bosun, started fresh by the user's tap...", and `console.RESUME_PROMPT`, "Started
again by the user's tap, after a Stop...": the check matches each word for word, so it reads
the two constants and a rewording changes both at once, c-731; a session started under an
earlier wording that the user never typed into reads as a hello), what the harness put there
(a reminder, a command echo, a compaction summary, a meta record, which is how a relayed
drain message is recorded), a tool's result, a subagent's thread. The rule is the handoff
note's (`consolehandoff.said`). It is asked on every state, so each transcript is read once
and then only what was added; a line caught half written is read on the next ask; and once
a hello is found for a console no transcript is looked for again. It reads the harness's
own record and never a terminal.

**Noticed while the page is open** (c-729). A message in Bosun's session writes nothing on
the board, so the state's revision did not move and a page on Meet Bosun was answered 304
until some other write: the hello showed only on a reload. While the step is on screen,
Bosun is running and no hello is seen, the page asks `GET /api/hello` (one timer at a time,
quietly; `watchHello` in `app/ui.startbosun.js`), which answers `said(cfg)`
(`firstrun.hello`). It is a read, not a setup verb (r1.F6): it takes no setup lock, so a
setup tap at the same moment is never refused as busy. The deck drops its documents and
tells the pages only when the answer changed (`Deck.heard`, r1.F7), so the state read after
a yes carries the hello and the step's Done, and a no moves nothing. Since a no redraws
nothing, the watch sets its own next ask (r2.F1): one timer at a time, every three seconds
for the first minute, then every ten, for as long as the page shows the step
(`K.startStep`), Bosun is up and no hello is seen.

**A session Keel cannot see into** (`bosunhello.hidden`, c-678 review). Where Bosun runs as
another user its transcripts are that user's alone: one that cannot be opened, or a folder
of sessions that cannot be listed, is not "no hello". The step then is not held on a hello
it could never find: it reads done and not confirmed (`sure` false, `hidden` true) with
"Bosun is running. Shipyard cannot see into its session from here, so it cannot tell whether
you have said hello", and the row says "Shipyard cannot see into Bosun's session from here, so
this row cannot turn green. Go on when you have said hello." The transcript is not read the
way the Bosun page reads one as its owner: that path is the console's own.

**What the design asks that the code has no place for.** "Copy details (the refusal and the
last log line)": the page has the refusal (the `console.start` answer, kept by `K.refused`)
and no log line, since a start that fails leaves none the deck reads. Copy details copies
the refusal alone.

`K.refused(verb)` and `K.refusal(verb)` (`app/ui.core.js`) are the last refusal of a verb in
the server's words, kept until that verb next goes through: `K.act` answers null for a
refusal and says it in a toast that is gone in seconds, so a screen that must keep saying
it reads it there.

### Add your repos (c-678)

The screen is `app/ui.startrepos.js` (`K.reposScreen`), the first-run design's step 4.

- **The choice at the top** (c-729). Under the space's name, one visible choice of two
  (`K.startChoice`): **Copy a repo**, from its URL or from the path of a folder on this
  computer, and **Use a folder in place**, Setup's Attach with what it costs. Only the
  chosen one's form is drawn. The address field is labelled "Repo address or folder" and
  says it takes a path too; a path that starts with `~` is read as the home folder
  (`reposetup.add_repo`), since git does not read it so. On the stranger run "Use a folder"
  was folded under the form and the field said only "the URL you would give to git clone".

- **One space for the user's code** (decision `space`). The space is named at the top,
  `work` unless the user types another, and it is fixed once the first repo is in or on
  its way. Personal keeps the builder's own cards and errands. Where the install already
  has a space beside personal, that one is the space and its name is not asked. The space
  is not made by a tap of its own: the first Add makes it.
- **Several repos.** Every repo is a panel with its state (`ready`, `copying`, `needs
  you`), its address and Remove. A ready one is one line, "Copied. It has a home address,
  and the <branch> branch is out.", from two facts the report now carries per repo:
  `origin`, the address of the space's remote, and `branch`, what the copy has out
  (`onboarding.repo_row`). A copy missing either shows the three checks (Copied, Has a
  home address, Main branch) with the one that does not hold as a stuck line. **Add
  another repo** is always there ("Add a repo" while the list is empty): the address, a
  short name filled from the address as it is typed, and Add repo; the fields clear after
  each add.
- **One add at a time.** The server runs one setup change at a time (and reads the config
  again after each, "The page never blanks" above), so the page keeps the adds it made in a
  list and sends the next only once the Setup report is back. An address added while another copies shows as a panel
  waiting its turn. The repo being copied is the row marked working (`adding-<n>`, the
  `row` of `change`), never the form, so the next address can be typed and added during a
  copy (r1.F4).
- **A copy that failed** stays in that list as a panel that needs you. `git clone`'s own
  words are sorted by `keel/cloneerrors.py` (`sort`), and the refusal carries the result
  as `detail`:

  | Kind | When | The sentence | The fix on the page |
  |---|---|---|---|
  | `private` | github.com would not say who is asking | "GitHub did not let this computer read <owner/repo>. Private repos need this computer to be signed in to GitHub." | **Connect GitHub**, where the GitHub connection is offered (below), else Try the copy again |
  | `host` | the same on any other host | "<host> did not let this computer read that repo." | what that host needs (a key or a saved password for git), and Try the copy again |
  | `nosuch` | the host says there is no such repo, does not resolve, or a path is no repo | "There is no repo at that address. Check the spelling, or open it in your browser to make sure it exists." | Edit the address: it goes back into the form |
  | `ssh` | an SSH address and no key the host accepts | "This address uses SSH, and this computer has no SSH key that host accepts." | Use the https address, one tap |
  | `hostkey` | an SSH address on a host this computer has never connected to ("Host key verification failed") | "This computer has not connected to <host> over SSH before, so the copy stopped before it began. Use the https address, or connect to it once in a terminal and say yes when it asks whether to trust the host." | Use the https address, one tap, as for `ssh`; then Try this address again |
  | `other` | anything else | "The copy failed: <git's line>" | Try the copy again |

  Under the sentence is git's own line as it came, and the line ends with Bosun's session
  like every stuck line. A failed copy left nothing behind on the server, the space it
  made included, so the panel is the page's alone and a reload drops it.
- **Use a folder I already have** is Setup's Attach form, folded, with what it costs: "Shipyard
  will merge finished work into that folder's main branch. If you also work there, a
  landing is refused while you have uncommitted changes. A copy is safer."

**A refusal may carry `detail`.** `actions.ActionError` takes what a verb sends beside its
sentence, `/api/action` answers it as `detail`, and the deck keeps it with the sentence
(`K.refusal(verb)`). A failed copy's kind is the one use so far.

**Connect GitHub** (c-678). A private copy that GitHub refused has one button where the
install offers the GitHub pack ([packs](62-packs.md), "The GitHub pack"). It opens that
pack's requirement rows inside the repo's panel, the same rows Where finished work goes
draws: one per check (`report.packs`, `packs.checks`), a ready row when it passes, and when
it does not, the stuck line with the fix the pack wrote (`K.fixOf`: the sentence, `gh auth
login` with Copy for the sign-in, and how you know it worked). Under them, **Check again**
(the Setup report read again, `K.setupParts.again`) and **Try the copy again**, which
sends the same add. Opening it sends nothing and turns no pack on: signing this computer
in to GitHub is what the copy needed, and whether the space ships through GitHub is the
later step's question. With no GitHub pack offered the panel keeps Try the copy again.

GitHub answers "not found" for a private repo once this computer is signed in as somebody
who cannot see it, so that reads `nosuch`; and with no sign-in at all it asks who is
asking for a repo that does not exist too, so that reads `private`. Neither can be told
apart from git's words, and both sentences ask for the thing to check.

### Set up your repos with Bosun (c-678)

The screen is `app/ui.startdrafts.js` (`K.draftsScreen`), the first-run design's step 6. It
replaced the tier in a box with Propose, which are Setup's still. The page draws no
conversation; it has three parts:

1. **Hand over to Bosun.** "Open Bosun's session and tell it to start.", the attach command
   with Copy, "Or open Bosun in the Claude app.", and a first thing to say with Copy:
   `Set up my repos.` Under it the line for the form chosen: Full "Bosun can also run the
   prepare and test commands in a copy to prove they work.", Guide "Bosun explains and
   asks. Where a command has to run, it gives it to you."
2. **What Bosun will ask about**, three things, "a conversation, not a form": how to prepare
   a fresh copy and run the tests; whether sessions may run the app (until that is written,
   sessions run tests only); conventions it could not infer. Where finished work lands left
   the list in c-734: no line of the file decides it. Bosun's draft brief
   (`tiercards.DRAFT_BRIEF`) says what each line it writes makes Shipyard do
   (`repofile.DOES`, one sentence per line), tells it not to ask where work lands, and has an
   ask whose answer moves something say so in that option's text; the shipped `asks.md`
   carries the same rule for every ask.
   A ready or adopted row whose file still names a branch to land on shows it under Lands on
   with "not read. Shipyard moves nothing for it." and where a card lands instead.
3. **What came back.** One row per file Bosun drafts, from `keel/tierdrafts.py` (`rows`):
   each repo the install copied into a space, in the config's order, then the space's own
   file, "CLAUDE.md (workspace)", once the space has more than one such repo (below). A row
   is its label (`<key>/CLAUDE.md`), its full path and a state, read each time and never stored:

   | State | Read from | The pill | The row shows |
   |---|---|---|---|
   | `idle` | the tier is its template, with no open proposal card or one nobody has started | not started | the path; Open a draft for Bosun where the tier has no card (`setup.tier.draft`) |
   | `drafting` | the card is at planning or building | Bosun is drafting | the path |
   | `ready` | the card is at review | ready for you | the lines Keel reads from the draft, Read the draft, Adopt |
   | `adopted` | the tier is no longer its template, and no card is being drafted or ready (a new card nobody has started changes nothing yet) | adopted | the same lines, Read the file |

   An adopted repo row also carries `lines`, whether those lines RUN, from the record of
   what the user adopted or saved (`tierdrafts.lines_of`, on the light rows too): `run`
   says nothing more; `changed` shows the pill "changed since" and "This file changed since
   it was adopted or saved, so Shipyard runs none of its lines and will not land this repo's
   cards. Read the file, then press Keep this text.";
   `never` (no record: a file from before records were kept, or written by hand) shows "not
   saved yet" and "This file has not been adopted or saved yet, so Shipyard runs none of its
   lines. Read the file, then press Keep this text to turn them on." A file that names no
   line has none to say this of, unless it changed since its record, which is said whatever
   it names now. **Keep this text** is under the open text only, so the text is read first;
   it is the Setup page's own Save (`setup.tier.save` with the row's space, key and exactly
   the text shown), the user's tap, which records that text and turns its lines on. The
   same sentences on a card and at the gate name the place: "(Setup, the <key> repo's
   file)".

   The lines are Prepare, Test and Lands on, each with the line of the file it came from
   (`keel/repofile.py`): they are lines of the CLAUDE.md, not form fields. Read the draft
   opens the text under "Draft of <path>", with Adopt, Tell Bosun what to change and
   Close. **Adopt** is `setup.tier.adopt` for the draft's card, the one writer every
   proposal has ("Propose and adopt", below), and nothing is written before it. **Tell
   Bosun what to change** sends nothing: it says to tell Bosun in its session, that the
   draft updates when Bosun has changed it, and gives the command.

**The workspace CLAUDE.md, with more than one repo** (c-678). What is true across the repos
of a space has nothing to say with one. So the space tier is a row of this list, and a
layer of How Keel remembers that is not dashed, only once the space has two repos the
install copied. The copy of the second leaves its draft card, `Draft the <space>
CLAUDE.md` (`clone_repo`'s `workspace`, the same `tiercards.open_draft`, whose brief names
every copied repo of the space and carries `etc/claude-md/space.md`); a later copy files
another only when none is open. Its row shows no commands, is read and adopted like any
other into `<install>/spaces/<space>/CLAUDE.md`, and is NOT required: the step is done by
the repos' files alone.

**The list follows Bosun.** The states come from the step on the state document
(`firstrun`'s `rules` step carries `drafts`, the rows without text and with a `stamp`, the
time the draft or the file last changed), so they move on every poll. The text and the
lines come from the Setup report (`spaces.<name>.drafts`), which the page reads again,
once, whenever the states or a stamp moved.

**Skip for now** says what is lost, "Sessions will work in these repos with no guidance and
will run tests only if they can find them.", and skips the step. Next turns on when every
repo's CLAUDE.md is adopted.

**Bosun is not running.** A check at the top says "Bosun is not running, so nothing is
being drafted. Bosun reads your repos and drafts these files with you in its session.",
with Start Bosun (`K.bosunStart`, the tap Meet Bosun has) and no "or ask Bosun" part; every
row not yet ready or adopted reads "Bosun is not running".

Where this stands: on the draft cards a copied repo leaves and Bosun stages ("Propose and
adopt: the audit", below, and [Bosun](96-bosun.md), "The setup conversation").

### How Keel remembers (c-678)

The screen is `app/ui.startmemory.js` (`K.memoryScreen`), the first-run design's step 5. It
is read only: one picture of the four layers a session reads, top to bottom with "then"
between them, and for each layer one sentence of what it is for and three lines: where it
lives, who writes it, who may change it. It has no button and sends nothing.

| # | Layer | Where it lives (`start.memory` on `/api/setup`, `firstrun.memory_panel`) |
|---|---|---|
| 1 | Workspace CLAUDE.md, tagged "only with more than one repo" and drawn dashed while no space has two | each space's tier, `<install>/spaces/<space>/CLAUDE.md`, for a space with a repo the install cloned |
| 2 | Each repo's CLAUDE.md | each such repo's tier, `<install>/spaces/<space>/<key>/CLAUDE.md` |
| 3 | Rules | Keel's house contract, `etc/house-contract.md` in the code Keel runs, and the rules a pack adds |
| 4 | Bosun's own memory | the install's `memory/bosun` (`console.memory_dir`, c-722) |

Under the picture: "Every card's session reads the first three; Bosun reads its own memory. They are plain
files in your repos and your install. Nothing here is hidden, and nothing is written
without you seeing it first." and, bold, "Bosun writes the first draft of each with you in
the next step."

**Bosun's memory is the install's** (c-722). The page shows the directory Bosun really
reads (`console.memory_dir`): `<install>/memory/bosun/`, seeded at init, or the checkout's
`bosun/memory/` for an install that has not run `shipyard move-personal` yet
([Bosun](96-bosun.md), "Where the memory lives"), since a path that is not there would be
the one wrong line on a page whose point is that nothing is hidden.

### Where finished work goes (c-678, c-758)

The screen is `app/ui.startlands.js` (`K.landsScreen`), the first-run design's step 7,
headed "Where does finished work go?". Its lead says what the page is for: work has to get
from this computer to where the team sees it, a connection does that (it opens the work on
the team's code host, as the user), and the user chooses one of the ways below. It then
separates this page from How work ships (c-758, the owner's word: the two read as the same
thing twice): "This step picks the tool that carries work to your team's code host. Your
team's process (which branches, who approves) is not asked here: that is How work ships, a
later step." (later, not next: a connection's own step may sit between them). One block
per space. One word is used on this step and the next, and in every sentence the server
hands them: **connection**. "Pack" is said only where a folder or a file is named.

**Four choices, each saying what happens next** (c-758; three until then, c-729). The first
teammate to set Shipyard up (2026-10-12) could not tell what the page was for, and the way
to add a connection someone shared was not on it at all, only on the Setup view. Every
space draws the four as one radio group (`K.startChoice`, `app/ui.start.js`), two rows of
two on the desk and one column on a phone, under the line "Pick one to see what it takes.
Nothing changes until you press a button inside it.":

| Choice | Its one line | What its section holds |
|---|---|---|
| **Use a connection Shipyard ships** | "Shipyard opens each pull request on your code host, as you. Next: turn one on and see what it needs." (the space's own noun, `K.say`), and "Shipped: gitea, github" | each connection found in the code's own folder (`folder` null on its row), with what it still needs in one quiet line ("needs: GitHub sign-in") and **Turn on for <space>**; Look again |
| **Add a connection someone shared with you** | "Your team has its own. Next: copy one command, run it, then turn the connection on here.", and "Shared with you: team" once one is there | under "Shared with you", each connection that is a clone of its own in the install's packs folder (`own_repo` on its row), marked "Found in <its folder>" (`folder`, `packsetup.install_folder`), with its quiet line and Turn on; then the one command with the install's real folder filled in, Copy, and Look again; then, under the plain heading "Found in this install", anything else that folder holds (r1.F7: one Bosun drafted for another space, the user's own import), which is listed and never called shared. While the space is on a connection a row here has no Turn on, and both headings say why: "(to use one, turn team off first)" |
| **Have Bosun draft one for another provider** | "For a code host Shipyard does not ship yet. Bosun writes a connection as a card: code you read, then turn on. Next: tell Bosun which host, approve its plan, then turn on what it builds." | the box, the tap, and the check that follows the card (below) |
| **Keep work on this computer, and push when you say** | "Needs nothing set up. Work is merged here, and nothing leaves this computer without your Push." | what happens, the space's two switches, and the push check (below) |

The first choice is left out only where no connection ships and none of them is in use (a
scratch report with no packs). The shipped choice says "Matches your repo." where a copied
repo lives on github.com and the GitHub connection ships; nothing else claims a match (until
c-758 keeping work on this computer said it for any other host, beside two other choices
that fit such a host as well).

**Picking is separate from turning on** (c-758). A choice opens its section and writes
nothing: `picked` is kept on the page, and `pick` only redraws. The button inside acts:
Turn on (`setup.pack.on`), Turn off (`setup.pack.off`, asked once, in the connection's own
row), Have Bosun draft a connection (`setup.pack.draft`), and, on a space that is on a
connection, **Keep work for <space> on this computer** (`setup.pack.off`), under a sentence
that says the tap turns that connection off. Until c-758 picking the first option with
exactly one connection listed turned it on at once, and picking the last one asked to turn
a connection off. A line under the choices states what is true now, whichever choice is
open: "Work for <space> now goes through <connection>." (the sentence `packsetup.pack_on`
also answers with, `went_through`) or "Work for <space> now stays on this computer, and you
push when you say." What a Turn on and a Turn off write is unchanged.

What is **in use** is the config's (a space on a connection, by where that connection was
found, else this computer) and is tagged so. What is **open** is the choice tapped, else
the one in use, else the draft while one is open or has landed for this space, else the
shared choice while a cloned connection nobody has turned on waits there (`own_repo` on its
row and no space on it) or a folder of the install's own has a problem
(`packs_error_install`, r1.F13), else this computer. So a teammate
who has just run the command opens the step on what it found.

**A connection that is on** is drawn in full, in its own choice's section: its row as the
Setup view draws it (`K.setupParts.packRow`: each check, a failing one as the stuck line
with its fix, and Turn off), the space's capability rows, and Look again. Each check is
drawn once (c-758): a capability row that a failing check holds up (`needs` on the
readiness row) is that check, so it is not drawn a second time under it. A row the space
cannot use at all (`declared` false: "the github connection has no tracker") is not drawn
either. While a space is on a connection the other sections offer no Turn on and say why:
"work is on team now. To use another, turn team off first, under "Add a connection someone
shared with you"." (the server refuses a second Turn on).

**No problem line points at a control the step lacks** (c-758). The report carries the
problem lines twice, in each page's own word (r1.F7): `packs_error` says pack, for the
Setup view, and `connections_error` says connection, for this step
(`packsetup.listing`). A line about a folder of the install's own packs folder (one under
the wrong name, "... holds the connection team: rename it to <folder>, then Look again.",
or one the packs repo still tracks: `packs_error_install` true) is drawn in the shared
section, which then opens by itself and says "A folder in this install needs a look". A
connection that does not load names no folder of its own, wherever it lies, so it is not
blamed on the install (r1.F13): its line is drawn under the choices, headed "A connection
does not load, so none is listed:", with Look again, and opens nothing. A misnamed folder
somewhere else (a packs folder outside the install) leaves every other connection listed,
so the same block is then headed "A folder Shipyard reads connections from needs a look:"
(fix check D1: none is listed is said only when no row is). A pack's own fix
often ends "then check again": the shipped section, the shared row and every connection
that is on have **Look again** (`K.setupParts.again`, which reads the report and writes
nothing). Until c-758 the step had no such button.

**A connection with no code host still lists, and says so on its row** (r1.F7): "mine has
no code host: it cannot open work for review." (its pack row's `capabilities`), on a row
that is on as well as one that is not. It is never filtered out: a teammate who has just
cloned a tracker-only one must see it.

**The shared one is a command the user copies** (c-758, the owner's decision). The text,
the command and its Look again are the Setup view's own (`K.setupParts.sharedPack`,
`app/ui.setup.js`), so the two pages cannot say it differently, but for the one noun
each page uses (`opts.noun`, r1.F7: pack on the Setup view, connection here): "Run this in a
terminal, with the address your teammate gave you and the connection's name. It goes in a
folder of its own here, named for the connection:", `git clone <its address> <install>/packs/<name>`
with Copy, and "Shipyard does not run it for you. When it has finished: **Look again**".
Shipyard does not clone for the user and never handles a repo's address or credentials.
What a clone is, and how a misnamed folder is said, is [packs](62-packs.md), "A pack
someone shared".

**Review requests** (c-730). Under a connection whose pack declares `reviews` (the pack row's
`capabilities`, `packsetup.pack_row`), and only once it is on, one question in plain
words: "Also bring me pull requests that wait on my review?" (the space's own nouns,
`K.say`), with "Off unless you turn it on. Each one becomes a review card: a house reviews
the pull request, and you choose what is posted. One from a fork waits for your tap, even
with auto review on, and its code is read, never run." Its answer is the space's `review_scan`
in the Settings form's own field, so it saves as every setting does; the GitHub pack starts
it off (its `[space]`). Ticked, before Save as well (`K.settingShown`, `app/ui.settings.js`),
the same form offers the space's `review_auto` and `review_model`, the settings the drain
files each review card with. Nothing else turns reviews on for a space. A value a space's
pack sets is that space's default in the form (`settings.pack_defaults`, reading `Space.pack_space`, the table `config.adapter_of` laid for `pack =` and none for `adapter =`, r1.F6; `default` on the
value row): the field says "from the pack" with no Reset, and a Reset after a save goes
back to the pack's value, not Shipyard's (until c-730 it said "from the pack (default on)"
beside an unticked box).

**Keep work on this computer.** The design's paragraph, the two switches of the space as
the Settings form's own fields (`fetch_before_work`, `offer_push`, so they save as every
setting does; both default off and are written on for a space made while the first run is
not finished, `reposetup.add_space`), and one check, "This computer can push to origin": a
dry run of the push per copied repo (`land.push.check` {`space`}, `landpush.check`). It
reaches the network, so it waits for the user's Check and is never run on a poll; a repo
that cannot push is a stuck line with what git said.
`start.lands` on `/api/setup` (`landpush.panel`) carries, per space with no pack, its
remote, its two switches and each copied repo with its host and the branch a card naming
no base lands on (c-734: the remote's default, `merging.usual_branch`, not the checkout).
What fetch and push do is [flows](64-flows.md), "Fetch before work, and a Push by the
user's tap". Above the choices the page says what it read: "Shipyard read api's address: it
lives on github.com. Pick how its work should arrive there." (the first copied repo that
has a host).

**Have Bosun draft one.** "For a code host Shipyard ships no connection for. Bosun writes
the connection as a card: you read its plan and approve the result, and nothing changes
until you turn the connection on. Until then, work stays on this computer, which works
with any git host." For a space that is on a connection the last sentence is "Until then,
work for work keeps going through github." A box, "Which code host, and what should
Shipyard do there?" (c-758, the owner's word: it read "Which provider, and how does your
team review changes?", the process question, which is How work ships'), with what a
connection can be asked to do under it ("What it can do there: open each card's change for
review, watch its checks, and bring review comments back to the card. Say which of these
you want, what your host calls them, and how you sign in to it."; no host's own noun is
spelled, since the host is not known yet and `make drift` keeps those out of core),
whose placeholder is an example of what to write (c-729, the owner's call: grey text that
goes on typing, never prefilled): which host, what to open for each card and into which
branch, what to watch and bring back, and how sign-in works, on GitLab, a host no pack's
drift terms name. The words still go to Bosun verbatim in the brief, and an empty box is
refused in the same question (`packdraft.CONNECTION_ASK`); and **Have Bosun draft a
connection**: `setup.pack.draft` {`space`, `words`, `reviews`} (`packdraft.draft_connection`). Above
the button, one more question, unticked by default (c-730): "Should it also bring you
pull requests that wait on your review?"; ticked, the brief has Bosun claim the review
verbs too (the kit has them: its layer's `review_requests` and `post_review` are what they
need), else leave review scanning out. In
the pattern of Import my Claude setup, it files one card on `packs` for the in-app
builder, at `assigned`, titled `Draft a connection for another provider`, whose brief is
the whole of it: the user's words verbatim, the checked starting point on the pack kit
(`keel new pack <name> --kit --into <its clone of packs>`, [extending](63-extending.md)),
the format and the rules. Since c-735 it has Bosun write only what is the host's own (the
host layer, its stand-in and its sentences), never copy another pack or a part of one, and
call the draft done when `keel pack check <its pack>` is green; never a token in the pack.
The card is attended, so it shows its plan first.
One draft at a time; refused with no words, and with no in-app builder that builds
`packs`. The form is hidden only while a draft is open (r1.F4): once one has landed it is
drawn again under what that one left, headed "Draft another connection", with **Have Bosun
draft another connection**, for a first draft that was for the wrong host or not right. Under it the check **Draft of the connection** follows that card
(`builder.connection` on `/api/setup`, `packdraft.connection_cards`).

**What a draft is, said before the tap** (c-734, the owner's ask): under the paragraph, and
kept while the card runs, "Drafting a connection is a real build. Bosun writes a plan
first, for you to approve, then builds the whole connection with its tests. That can take
around 40 minutes and add a few thousand lines: an estimate, not a promise. You can carry
on with the other steps meanwhile: press Skip below, and this step stays open until the
connection is on. The check below shows where it is, and the card shows on Now when it
needs you." (The second stranger run's drafted connection took about that.)

**Honest states** (c-758). A draft never reads as done before a connection is on:

| State | The choice's quiet line | The check | The step (`firstrunsteps.draft_waiting`) |
|---|---|---|---|
| A draft in progress | "In progress (c-12), not finished" | checking: "Not finished yet. <where it is> (c-12). <whether Bosun has been told> Until it has landed and you turn it on, work stays on this computer.", with **Open c-12** | not done: "Bosun is drafting a connection for work (c-12); until it has landed and you turn it on, work is merged on this computer: skip this step to carry on meanwhile" |
| Landed, not turned on | "Drafted (c-12), not turned on yet" | needs you: "c-12 landed: the connection forge is here, and it is not turned on yet. Work for work still stays on this computer.", fix "Press Turn on for work just below.", and that connection's row with its Turn on right under it | not done: "the connection Bosun drafted (forge, c-12) has landed and is not turned on for work: turn it on, or skip this step to keep work on this computer" |
| Landed and on | none: the choice is in use | ready: "c-12 landed, and forge is on for work." | the connection's own rows |

A space that is on another connection while a draft for it stands is told so (r1.F1): the
check says "Work for work goes through github." in place of "stays on this computer", the
landed check waits (no Turn on is drawn there, since the server would refuse it), and the
line under it says where the Turn off is ("work is on github now. To use another, turn
github off first, under "Use a connection Shipyard ships".").

Where the connection in use is not listed (r2.F1: one connection that does not load
empties the list, so its row and its Turn off are not drawn), the line names the control
that is drawn: "work is on github now, and github is not listed because a connection does
not load. To use another, press Keep work for work on this computer under "Keep work on
this computer, and push when you say", or fix the connection and press Look again." That
tap (`setup.pack.off`) goes through in that state. When the connection that does not load
is the one the space is on, the config itself is refused, so the step is never drawn then.

One draft slot is install-wide, so a space the draft is not for sees it too, and is told
whose it is (r2.F4): "Not finished yet, and it is for team. <where it is> Until it has
landed and is turned on, work for work stays on this computer." (or "goes through github.").
The line "press Skip below, and this step stays open until the connection is on" is said
only to a space on no connection, the one the step waits for; a space on a connection
reads "You can carry on with the other steps meanwhile."

Where it is, while the card is open, is the gate that waits on the user first ("Waiting for
you to approve its plan", "Ready for you to approve": `gate` on the open card), else its
stage, then whether Bosun has heard of the user's last tap ("Bosun has been told." or "Bosun
is told as soon as it is free.": `told`, [Bosun](96-bosun.md), "Telling Bosun"). The landed
connection is `builder.connection.pack`, the pack its landing's merge added
(`packdraft.drafted_pack`), drawn under this choice in the space it was drafted for only
(r2.F4: the draft card is filed in personal, so its target space is recorded on it at
create, `options.target_space`, and said as `builder.connection.space`). In any other space
it is listed under the shared choice, as found in the install's folder, and the check there
waits and says so: "c-12 landed for team. The connection forge is listed under "Add a
connection someone shared with you", with its Turn on for work." (r2.F4: it says whose
draft it was, and promises the Turn on only where this space's row has one: a space on a
connection reads the sentence up to the choice's name). That
choice is named only when the row is really there (r1.F3: the connection loads and lies in
the install's folder); a landing whose connection cannot be read, or no longer loads, says
"c-12 landed, and no connection from it is listed on this install. Open the card to see
what it added, or press Look again.", with both buttons. A landed draft that is not on is
never drawn as ready. The step
holds only while the space the draft is for is in the config and on no connection, only
while the landed one still loads and names its space, and never for an archived card. A
landed draft holds it whatever another open draft is for (r2.F3: an open draft for a space
on a connection holds nothing itself, and no longer lets the landed one go); a
draft for one space does not hide what another space's connection still needs (both are
said). The way past it without a connection is Skip, which is what keeping work on this
computer means there. The state is built on every poll, so the drafts are read light
(r1.F9, `packdraft.standing`): one query by title, as `firstrun.WATCHED` reads its cards,
never the whole board, and the connection a landed draft added is asked of the packs repo
and kept as any reading is (`readiness.kept`, five minutes, `KEEP_SECONDS`), so the builds
between two readings start no process. A read that could not answer is kept only
briefly (fix check D2, `retry_failed`): when git cannot say what the landing added, that
is kept for half a minute (`RETRY_SECONDS`) and then asked again. So a failure that passes
never lets the step go for five minutes while the page shows the landed draft, and one
that never passes (a merge the packs repo no longer holds) costs one git process per half
minute, not one per build.

**What done means is said on the step**, under every block, and it follows the state
(r1.F2). While a draft stands for a space on no connection (open, or landed and not on):
"A connection draft stands, so this step is not done yet: it is done when that connection
is turned on and everything it needs is ready. To keep work on this computer meanwhile,
press Skip below." (Skip is the frame's own; there is no second way to skip.) Otherwise:
"This step is done when a connection is turned on and everything it needs is ready, or when
you keep work on this computer." (`integrations_state`: a space on a connection waits for its rows; with none
anywhere there is nothing to check, and the step reads done once the user has been through
it, `firstrun.seen`.)

**The page follows the board** (c-734). The Setup report is read on the page's own actions
and on Look again, never on the poll. The state carries `firstrun.watch`
(`firstrun.watch`), a short stamp of every card the setup page draws from the report: the
tier, flow and connection drafts and the import, by id, stage, block, last change and the
newest `tell` or `wake` (review r1.F5: "Bosun has been told" follows the wake), read for
open cards and ones that moved in the last `WATCH_DAYS` (r1.F10), on the light state of a
finished install too, so Setup follows after Finish (r1.F8).
Start and Setup read the report again once whenever it moves (`follow`,
`app/ui.setup.js`), so a draft staged by Bosun, approved in another tab or landed by the
drain shows with no reload; on the second stranger run the landed connection still read
planning until a reload.

**A connection's own step does not repeat the checks** (c-758). A pack's `[[setup]]` step
sits right after this one ("Connect GitHub", `firstrun.order`, headed "From the github
connection, for work."). It draws its text, each numbered line a line of its own, and then
how its checks stand in one line, since this step has just shown each of them with its fix:
"1 of 4 checks still needs you: GitHub address. Each one is on Where finished work goes,
with its fix." or "All 4 of its checks pass. They are on Where finished work goes.", with
**See the checks** (back to this step) and Look again (`packStep`, `app/ui.start.js`).
Until c-758 it drew every check again, fix and all. That holds only for a step that follows
this one (r1.F5: `after` on the step's entry, `firstrun.order`, "integrations" unless the
pack says otherwise). A pack may place its step after any core step; such a step draws its
checks with their fixes as before, and points back at nothing, since the user has not seen
them on the screen before it.

Where the design and the code differ: the design's fix for a computer that cannot push to
github.com is "the first three checks of A" (gh installed, signed in, git using that
sign-in). The GitHub pack has no check of its own for git using the sign-in (`gh auth
login` over HTTPS sets it), so the line names the first two.

### How work ships (c-678, c-732, c-758)

The screen is `app/ui.startships.js` (`K.shipsScreen`), the first-run design's step 8,
headed "How does your team ship its work?", with the lead: this page follows from the one
before and starts from what you chose there; you answer question 1 here (which branches
work starts from), and it applies when you press Save, to new cards only (r1.F3: Save is no
Adopt, so the page says what it does); the rest is already set by what you chose, and the
page shows it (the page, not the drawing: a connection with no code host has nothing
drawn); changing it is optional: if your team works differently, Bosun asks a few
questions and draws it again, and nothing changes until you press Adopt. The step's own
line says the same ("Question 1 is answered here; the rest is already set by what you
chose, and changing it is optional"). The owner's word after the first screenshots (c-758):
nothing said the Bosun part was optional, so a teammate with a connection on thought they
had to talk to Bosun. So the page is drawn in this order: what was chosen, question 1, the
drawing headed as already set with **Keep how it works now** as the normal way on, then
the Bosun questions under "Only if your team works differently", then how new cards start.
The step has nothing to check (`firstrunsteps.ships_state`): it is done by going on past it
(Next, Keep how it works now), never by the conversation. The numbered parts below are
numbered as the page numbers its questions, not in the order they are drawn. The owner's standard for it (c-732): a newcomer must see that Shipyard is ASKING how
their team works, the asking and the showing must be easy to take in, and what they said must
visibly match the drawing. Per space with a repo (every space when none has one), top to
bottom:

0. **What was chosen on the step before** (c-758: the first teammate could not tell that
   this page came from that choice). On a connection: "You chose github for work, so this
   page starts from it", then "What github does, in its own words" with the connection's
   own description (its pack row's `description`, read from the report, never written
   here), and that the drawing below shows that path while the questions are about the
   rest. On none: "You chose to keep work for work on this computer, so this page starts
   from that" once the choice step is recorded as seen (`seen` on its entry), else, for a
   user who skipped it or never opened it, "Work for work stays on this computer, so this
   page starts from that" with **Choose on Where finished work goes** (r1.F8); what that means, "If your team reviews work on a code host, choose a
   connection first.", and, while Bosun is drafting one for the space, "Bosun is drafting a
   connection for work (c-12). It is not finished, so this page still shows work kept on
   this computer." The button goes back to that step (`parts.open`) under the name that
   is true: **Change it on Where finished work goes** once a choice was made (a connection
   is on, or the step was seen), **Choose on Where finished work goes** when none was.

1. **"1. Where does work start?"**, answered on the page, with its example. The branches a
   card's work can start from; each card goes back to the branch it started from; you pick
   one on the card, and a card that picks none starts where it always did; Save applies at
   once, to new cards only. A space whose repos land on an integration branch is offered no
   choice: the page names that branch, and it is what the drawing shows (r1.F4, F5). The space's bases as chips, each with
   remove, a box and Add for another branch, and Save, which writes `[spaces.<name>] bases`
   through `setup.settings.save` ([flows](64-flows.md), "A space's bases"). With none saved,
   the repo's default branch is filled in and said ("main is your repo's default branch,
   filled in for you. Press Save to keep it."); saved, "Saved. Every new card offers main,
   staging.". A space whose pack declares its own base field edits nothing: a select of its own
   branches is named ("Your connection lists these, ..."), any other field is said to be on
   every new card (r2.F5).
2. **"Only if your team works differently"** (it was "The rest you answer with Bosun"),
   drawn BELOW the drawing: "This part is optional. If the drawing above is not how your
   team ships, tell Bosun how it does: a short conversation, in which Bosun asks the
   questions below and turns your answers into a new drawing. Nothing changes until you
   press Adopt, and no code is written." With nothing drawn (`flow.held`) it names no
   drawing above: "This part is optional. Nothing is drawn for work yet. To have your
   team's way drawn, tell Bosun how it ships: ...". Then that they are answered in Bosun's session,
   not on the page, one at a time, and that Bosun asks back anything it cannot place rather
   than guess; questions 2 to 5, each with its example (which
   branch finished work goes back into, who says it is good, what happens after that, when
   people see it live; question 2 was "Where does finished work go?" until c-758, the
   headline of the step before). **Start this with Bosun** files the card Bosun drafts on
   (`setup.flow.draft`), then the line follows it ("Bosun is ready to ask you (c-9)...",
   "Bosun is drafting (c-9).", "Reading Bosun's draft...", "Bosun's draft is above"), and the
   command to Bosun's session with Copy.
3. **The drawing** (`app/ui.flowpicture.js`, `K.flowPicture`): ONE diagram, each place once
   (c-732 review: a list of arrow rows repeated main three times and left the shape to the
   reader). Branches are boxes with their name and a few words on what each is ("your card's
   branch: one card's own work", "main: work starts here", "origin: your team's copy"); each
   move is one arrow, labelled with the move and who makes it ("Approve, you", "Weekly merge,
   a teammate", "Push, you"); a box a move of yours reaches is marked. The words agree with
   the connection's own (c-758): Ship is a button on the card, so its arrow is "Ship, you"
   and marked as yours (it read "Ship, Shipyard" beside a sentence that said you press it);
   and a step made on the code host reads "a teammate" in a flow a team wrote, which knows
   who, but "you or a teammate" in Shipyard's own general flow, which cannot know, as the
   shipped connections say of the merge ("You merge on GitHub."). That flow's sentence for
   the merge names the code host in the connection's own word (`{codehost_name}`,
   [flows](64-flows.md)). On a phone, a drawing with more arrows than places (the general
   flow's four between two) is too small to read, so its list starts open there. It is the deck's own
   diagram drawing (`K.boardDraw.drawGraph` on the board's line format, the ELK layout of
   `app/vendor/elk.bundled.js`, [the board](45-board.md), "A still drawing"): left to right in
   the order work moves on the desk, top to bottom on a phone, where the boxes carry the name
   alone and the arrows' words sit on the arrows, so it stays narrow enough to read. It is
   still (no pan or zoom) and shown whole. A flow's `{base}` is drawn as each of the space's
   bases by name (or the repo's default branch), a branch the flow names itself is the same
   place as the base of that name, and a move that names `bases` is drawn only to and from
   those. A space with no pack whose `offer_push` is on gets a Push arrow from each branch a
   card lands on. Under it, one sentence, "In words: ...", built from the arrows
   (`K.flowSentence`: where work starts, then each move once, Shipyard's own steps in its own
   words, any other move its `about`), and "The same drawing, as a list", folded. Every box and
   arrow, in the drawing or the list, can be tapped: the tap opens a line under the drawing
   saying what it is and how to change it (a base: "Change where work starts", back to
   question 1; anything else: tell Bosun, with the command), and that nothing changes until
   you press Adopt.

   | State | When | What the drawing panel shows |
   |---|---|---|
   | Default only | no proposal at review | headed as already set: "This is how github ships work for work, and it is already set" with a connection on, "Work for work is merged on this computer and pushed when you say, and that is already set" with none (it was "What happens now, until you change it"); "Keeping it is all most people do: press Keep how it works now and go on."; a space that ships by its own flow while a new draft of Bosun's is open is headed from what is drawn, "This is how work ships work now: your own flow", without that line (the opening panel is worded the same way, `drawnSaid`: "The drawing below is work's own flow, adopted in place of github's usual path." on a space's own flow, "of the usual path" with no connection on, and no drawing promised where nothing is drawn); the drawing and its sentence, "Only the arrows marked you are buttons on a card. The rest is a picture of what happens.", and **Keep how it works now**, which goes on to the next step (Kept once seen) |
   | A draft waiting | the space's open proposal is at review and its draft checks (`spaces.<name>.flow_draft`) | "Bosun has a draft: check it against what you said", **What you told Bosun** (the draft's `description`, which the brief asks for in the user's words), then Bosun's draft and How it works now, one above the other, each with its sentence, "Read the sentence under Bosun's draft...", **Adopt Bosun's draft** (`setup.flow.adopt`) and **Keep how it works now** |
   | Nothing to draw | the space's connection has no code host (`flow.held`, `flows.held`) | "Nothing is drawn for <space> yet", why in the server's own sentence ("A repo card cannot be approved in this space until a code host is set up (the team connection has no code host)."), and **Back to Where finished work goes**; the advice to turn on a connection that has a code host, or keep work on this computer, is given only for that reason (`flow.held_codehost`, r1.F8: `held` has two more, an older adapter with no publish or no ship verb, and those read as the server's sentence alone). The opening panel then does not promise a drawing. Until c-758 the box was drawn empty, with "In words: Work starts on main." |
   | A flow of its own | the space has its own flow and no open proposal | "Adopted. Bosun's draft is how this space ships now." where a proposal card of the space is done (`flow.adopted`), else "This space ships by its own flow."; the drawing, and "Tell Bosun in its session if you want to change it again." |

   A draft that does not check is said in the check's words and not drawn. A proposal at review
   whose draft the Setup report does not carry reads "Reading Bosun's draft..." while the page
   asks for the report again on a timer (every three seconds, five times, `K.shipsRetry`),
   then "Bosun's draft could not be read. Open its card to read it there, or tell Bosun in its
   session." with **Open <card>**.
4. **"New cards in <space> start as:"** (c-729), **Attended** ("It stops at its plan for
   you.") or **Autonomous** ("It plans and builds on its own."), `[spaces.<name>] autonomy`,
   and "You can change it on any card."

The step carries `asks` (the five questions, `bases.ASKS`, the list Bosun's brief asks from
too) and `bases` per space (`{bases, suggested, pack, listed, integration}`, `firstrunsteps.bases_of`: `pack` where the pack declares a base select of its own (c-734: a free-text field takes the space's bases, so the page asks for them), `listed` where that field is a select of its own branches, `integration` the branch every card lands on where all the space's repos have one), beside
`plans`. The page has no box to describe a flow in. The proposal's card and stage come with
the state on every poll; the draft drawn as a flow comes with the Setup report, read again
whenever the card or its stage moved.

**Where the design and the code differ.**
- Bosun cannot file a proposal card, so the page has one button the design does not:
  **Start this with Bosun** (`setup.flow.draft`), which files the card Bosun drafts on
  ([flows](64-flows.md), "A draft Bosun writes with the user").
- The c-678 design put the two pictures side by side; c-732 stacks them, the draft first, since
  a drawing of places and labelled arrows needs the width to be read.
- Keep how it works now beside a waiting draft goes on and leaves the draft at review, where it can still
  be adopted or archived from its card: nothing on the page discards it.
- The Flow panel in Settings keeps its own drawing (`K.boardDraw`) and its Propose box
  (`flowChange`, `app/ui.settings.js`), since that panel is how a space with no builder
  proposes a flow.

### A browser for sessions (c-678)

The screen is `app/ui.startbrowser.js` (`K.browserScreen`), the first-run design's step 9,
headed "Give sessions a browser to look with". It is optional: Skip is the frame's. Two
checks, in the shared check row (`K.check`):

| Check | States |
|---|---|
| Node.js 20 or newer (`browserinstall.node`, read from `node --version` and kept like the other slow readings) | ready with the version; else the stuck line with what is installed ("Node.js v18.19.1 is installed, and Shipyard's browser needs 20 or newer.", or that it is not installed) and the fix, with `brew install node` to copy on a Mac |
| Shipyard's browser is installed (`browserinstall.status`) | waiting, with **Install** (off until Node is ready); checking, with the server's sentence ("Getting the installer. The download starts in a moment.", "Downloading Chromium: 40% of 151.2 MiB", "Unpacking Chromium") and, where a size is known, a bar and "60 of 151 MiB"; ready; or, when the download stopped, the stuck line "The download stopped: <what the installer said>. Chromium had reached 40% of 151.2 MiB." with **Try again** and Bosun's session as the third part |

Install and Try again are one verb, `firstrun.browser.install` (`browserinstall.start`). It
runs `bin/keel-browser install` ([houses](20-houses.md), "The one browser tool") detached
from the deck, so a deck that restarts mid-download does not end it, with the tool's output
in `install.log` and its process id in `install.pid`, both in the browser's own folder
(`~/.keel-browser`, or `KEEL_BROWSER_HOME`). One download at a time; none is started while
Node cannot run the tool.

Nothing about the download is stored by Keel. Each state reads it again: `downloading`
while the process the pid file names is alive and is the installer (the download's own
shell writes its pid before the tool runs and removes the file last; a file left by a reboot
or a kill names some other process by then, so the command line is checked too and a stale
file is cleared, `browserinstall.is_installer`); `ready` when the package and a Chromium
build are there; `failed` when the process ended and they are not, with the tool's last
line and how far the archive was. While a download runs the page asks for the state again
every three seconds, so the bar moves. The readiness row `browser` says the same presence
([packs](62-packs.md), "Readiness").

**How far it is is the downloader's own count** (c-757, `browserinstall.progress`). It was
the size of the browser's folder against a fixed 400 MB, and on the first teammate's setup
(2026-10-12) it read 0, then 3, then done. The reason, read from the pinned Playwright
(`browserFetcher.ts`): the archive in flight is written to a `playwright-download-` folder
under the system's temp folder, not into the browser's folder, and unpacked into it in
seconds at the end. So for the whole download the folder held only the package npm put
there, 13 MB, which is 3% of 400. What the installer does print, into the `install.log`
this module already keeps, is one "Downloading <name> from <url>" line per archive
(Chromium, then FFMPEG) and then one line per tenth, "|...|  40% of 151.2 MiB". `percent`
is the megabytes those lines say arrived over the megabytes they say there are, summed over
the archives named so far, and never 100 before the browser is there. It moves in tenths
because the installer reports in tenths. Where the log names no size (the package is still
being fetched, or a downloader that prints something else) `percent` is None: the row says
what is known and the page draws no bar. An archive at 100% that the installer has not
reported as downloaded is being unpacked, and the row says so. An archive the installer
names again (it tries a failed one from another address, from nothing) counts from its
start, so the bar goes back, which is what happened. The step's text says "about 400 MB on
disk", which is the unpacked size; the archive itself is about 150 MB.

Where the design and the code differ: the design's fix reads "Try again (it resumes)". The
button is Try again and the page does not say it resumes: the package that is already
there is kept, but the tool fetches the browser's archive again from its start.

### Back up (c-678)

The screen is `app/ui.startbackup.js` (`K.backupScreen`), the first-run design's step 10,
headed "Keep a copy of your board".

**Off:** one field, Folder, filled with the suggested one (`~/shipyard-backup` in the user's
home), and **Turn on backup**: the one verb `firstrun.backup.on` ([backup](85-backup.md),
"Turned on from the first run"). A refusal stays on the page as a stuck line in the
server's words. For a folder inside the install it reads "That folder is inside the
install, so the backup would copy itself." and its fix is **Use the suggested folder**,
which fills the field and clears the line.

On a computer with no gpg where the backup looks, the step says so before the tap (a
stuck line "gpg, for backup" in the check's own words, from `step.backup.gpg`) and a tap
is refused by the server, which asks the check afresh. Either way the line's fix is **Open
Check this computer**, where gpg's row has the command that installs it.

**On** (`step.backup`, read with every state, `keel/backupstatus.py`). Each row is what
was observed when the state was built, never what is expected (c-757; the first teammate's
screen said "Done" over a spinner reading "The hourly job is writing it now." and a grey
"First proof on Sunday", for a backup that never wrote a copy):

| Check | States |
|---|---|
| Folder can be written | ready with the folder; a stuck line when the folder is not there or cannot be written |
| First copy written (`copy`) | `written`: ready with when. `writing`: checking, "The first copy is being written now, in the background. You can go on to the next step.", while a run holds the tool's lock and only then. `failed`: a stuck line with the reason the run left (`last_error`), what happens next, the log's path, and **Open Check this computer** when gpg is what is missing. What happens next is the drain's own rule (`keel/backupdue.py`): with no copy yet, "Shipyard starts another within a minute or two while this computer is awake, then again about every ten minutes, up to three an hour."; after a copy, "The next hourly run tries again.", with "The newest copy was written N ago. The run after it stopped: ..." as what happened. `none` (no copy, no run, no error): waiting, "No copy is being written right now. Shipyard starts one by itself within a few minutes.", for ten minutes after the turn-on; after that a stuck line, "No copy has been written since backup was turned on N minutes ago, and none is being written now." |
| Restore proof (`proof`) | `waiting`: "First proof on Sunday 18 October.", the real next day (", once there is a copy to prove." while the folder holds none). `proved`: ready, "Proved 2d ago. The next one is due Sunday 25 October." `failed`: a stuck line, "The last restore proof failed: <the tool's reason>", with "It runs again by itself on <day>" and the log. `missed`: the quiet stuck line, "The restore proof due Sunday 18 October did not run.", once the weekly time is twelve hours past with no proof and no failure since, and only when a copy of this install's was already in the folder at that time: a backup turned on after it, or whose first copy came after it, waits for the next one |

**Two honest states, and the way on.** The step is done once backup is on and a copy of
this install's has been written, and it never goes back (`backupstatus.verdict`):
"Done: backup is on, and the first copy is written, into <folder>". While the copy is
still to come the step is done for Next and not confirmed (`sure: false`): its line reads
"Backup is on, into <folder>. The first copy is being written in the background." with no
"Done" and no done colour, the step list says `copy pending`, the screen says "Backup
is on. The first copy is written in the background, so you can go on: press Next. This
page shows the copy once it is written.", Next is the primary button, and the page asks
for the state again every four seconds so the row turns by itself. The last screen's "What
was set" row says the same sentence. With no copy yet, a first run that failed, or a copy
that never started, is not done: the line is a warning in the step's words, and the step
is under "What was skipped" on the last screen with Set it up.

**Done is never said over a row that says otherwise** (review r1.F3, r1.F4). Once a copy
exists the step stays done, and what is wrong after it makes it not confirmed, with a word
of its own in the list and a line that names it, the first that applies:

| What is wrong | The list says | The step's line |
|---|---|---|
| the folder is not there or cannot be written | `folder missing` | "Backup is on, but <folder> is not there or cannot be written, so no copy is being made." |
| a run failed after the copy | `last run failed` | "Backup is on and has a copy, but the last run stopped: <its first sentence>." |
| the restore proof failed | `proof failed` | "Backup is on and has a copy, but the last restore proof failed." |

Each is still under "What was set" on the last screen, with that sentence: a backup that
is on and holds copies is not one to "Set it up". A missed proof stays on its row.

**Readings belong to this install.** The backup's home is one per user account, so a
second install on the account finds the first one's state file. A copy, a proof or a
failure counts only when it is not older than this install's turn-on (`since`: the
config's `[backup] since`, written by the turn-on). With no key, or one that is not a
time or is later than now, every reading is this install's own, as before the key
existed; see [backup](85-backup.md), "Turned on from the first run".

**The words.** Above the rows: "An encrypted copy of the board is written to <folder>
about every hour, when something on the board has changed. If a copy is overdue, Shipyard
starts one itself. Copies are kept hourly for a day and daily for thirty days. If none
succeeds, a notice appears on the board." For a folder on the disk the install is on
(`same_disk`; the suggested folder is, being in the user's home) a line says what that
means: "<That folder> is on the same disk as this install. Unless that folder is synced
somewhere else, a copy there does not survive losing the disk or the computer." It says
only what a shared device proves (r1.F7): a folder inside a synced folder shares the
home's device too, and is not told to go and pick a synced folder. It is drawn before the
tap too, while the field holds the suggested folder.

Right after the tap the page shows **Your recovery passphrase**, with Copy and the tick "I
saved it somewhere that is not this computer.". It is shown once: ticking it, or leaving
the page, drops it. Whenever no passphrase is showing (after the tick, after a reload, on a
page the tap's answer never reached) the panel says where the key file is, from the state's
own `key`: "The recovery passphrase is kept on this computer in <key file>. Without it a
copy cannot be read, so keep it somewhere that is not this computer too." The deck does not
restart after the turn-on: it reads the config again in place (c-729), and the first copy
is a process of its own that a restart would not end either.

Where the design and the code differ: a computer that already had a backup key (a second
install, or one set up again) is not shown a passphrase, since the key was made and shown
before; the page says so and names the key file.

### Your first card (c-678)

The screen is `app/ui.startcard.js` (`K.firstCardScreen`), the first-run design's step 11,
headed "Give Shipyard one small piece of work".

**Before a card is filed:** What to do, More about it, Repo (the repos that are in, across
spaces; the install's own `packs` is not offered) and **File and start**, which is `create`
with `start` in that repo's space. What the user wrote goes as their `words` (c-729): the card
gets a short title (`keel/cardtitle.py`: the first sentence, without the asking and the repo
it names, cut at a word to nine words and sixty characters) and the words are its brief, so
its branch and its merge subject on main read "Add a way to delete a note", not the whole
sentence. The merge subject cuts any title at a word to 72 characters too
(`merging.merge_message`). The repo chosen is always one of the list: the first
until another is picked, and the first again when the picked one is no longer in, so what
the list shows is what is sent. A landed card's Push comes with the card's own detail; the
page holds one card's detail at a time, so when another card's took its place the screen
asks for its own again, once.

**The card Bosun suggested.** Above the form, when there is one: "A first card you could
use. While drafting api/CLAUDE.md, Bosun saw that the README has no setup section. Want
that as your first card?" with **Use this**, which fills the form and sends nothing. It
comes from the board and nowhere else: a draft card's brief tells Bosun it may leave one
line, `kb note <card> "First card: <what to do> (because <what you saw>)"`
(`tiercards.DRAFT_BRIEF`), and once that card is done (its file adopted)
`tierdrafts.suggestion` reads the newest such note off it (`tierdrafts.first_card_of`).
Nothing is suggested before Adopt, and nothing once a card is filed.

**Once a card is filed:** its path, past review to landed. Each place is read from the card
as the state carries it:

| Place | When |
|---|---|
| Waiting for a session | `inbox` or `assigned` |
| Planning | `planning`, no plan gate |
| Your plan to approve | `planning` at its plan gate; on the path only where the card's space shows plans (How work ships), or the card is there now. **Approve**, **Send back** |
| Building | `building` |
| Checking its own work | passed once the card is at review (see below) |
| Ready for you | `review`, at its outcome gate. **Approve**, **Send back** |
| Landing | the approve is on record and landing, or the card is at `shipping`. A landing that was refused is the stuck line, in the sentence its reading gives ("The stuck states outside setup", above) or else the block as the board holds it, with **Send back with the failures**, which sends the block back as the reason |
| Landed | `done`: a link to what was opened, or, for a merge on this computer, "Merged into main on this computer." and **Push main to origin** (`K.pushLine`, [flows](64-flows.md)) |

Approve and Send back are the card pane's own verbs (`approve` with the gate, `sendback`
with the reason typed in the box that Send back opens), so the step is not a second way to
answer a gate.

**Where the design and the code differ.**
- "Checking its own work" is never where the card is on the page: nothing on the state
  says a house has left building for its own review before the gate, so the place is
  drawn and reads as passed once the card reaches review.
- The step reads done once the card reaches review, as before, so a card that waits on a
  teammate's merge does not hold the step open.

### You are set up (c-678)

The screen is `app/ui.startdone.js` (`K.setUpScreen`), the last place: `set-up`, with
nothing to check and no Skip. Nothing on it is stored: every line is a step's state as the
page already has it.

- One line of where things stand: "Shipyard is running, api, web are connected, and your first
  card landed." Each part is said only when it is true (the user's repos by name; the
  first card at `done`).
- **When something does not work**: "Bosun's session is where to go. Open it in a terminal
  with this command, or open Bosun in the Claude app (the session named Bosun).", the
  attach command with Copy, then when to go there.
- **What was set**: every step that reads done, in its own sentence (`why`), with
  **Change**, which opens that step; under Set up your repos with Bosun, each adopted repo
  file's prepare, test and lands-on as the file says them (`spaces.<name>.drafts`), only
  where Keel runs them (`lines` is `run`). A file whose lines are not on lists none and
  says so, "Its lines are not on: the file changed since it was adopted or saved." or "Its
  lines are not on yet: the file has not been adopted or saved.", with **Turn them on**,
  which opens that step.
- **What was skipped**: every step that reads not done, with **Set it up**. A step with
  nothing to check is in neither list.
- **More to set up later**, folded: the phone (the `tailscale serve --bg <port>` command
  and whether it is set; Keel only reads it) and voice (its row, the two engines with
  neither picked, the Settings field, and the link to the Voice page). This is what the
  Phone and voice step showed.
- **Open the board**, which sends `firstrun.finish` where Finish would go through and then
  opens Cards, and **Open Bosun**, a link to Bosun's own page on the deck (`/console`).

The frame's Finish is still there, as on every last step.

### Check this computer (c-679)

The step's screen is the first-run design's step 1. Its rows are `prereqs.gather`'s checks
(`start.prerequisites` on `/api/setup`), each named by its `label`. `keel/prereqs.py` holds
every word of a miss as data, so this page and `shipyard init` say one sentence
([install](88-install.md), "The checks, and what a miss says"): `what` is the stuck line's
What happened, `fix` and `command` are The fix (the command in a box with Copy), and
`required` decides the form: "needs you" for a check setup stops on, the quiet form with
"(does not block)" for one it does not.

The screen is its own file, `app/ui.startchecks.js`, loaded before `app/ui.start.js`,
which reads it as `K.checkScreen(report, step, parts)` and hands it its row and section
helpers.

**Your name and email for git** is the one row whose fix the page does itself. While git
has no `user.name` or no `user.email` its fix is two fields, Name and Email, and Save, with
"Writes git's global setting." beside it and no command. A field starts from what git
already has (the check's `values`), and one git already has is shown and cannot be typed
over: the server writes only what is missing and never rewrites a value git has
(`prereqs.save_identity`, [install](88-install.md)), and the page says the same. What is
typed is kept across redraws, Save with a field empty says so and sends nothing, and Save
sends `firstrun.identity.save`. The answer drops the kept readings, the report is read
again, and the row is a passing check that reads "Name <email>". The rule is in the deck
by the check's name (`git identity`), since it is the only check with a form.

When git's settings could not be read (the check's `unread`), the row says it could not be
checked, with Check again as its fix, and draws no fields: a Save would be refused.

The step's why line is readiness's `prerequisites` row, which says each miss as
`prereqs.miss_words` does (its label and what happened), so it reads as the row under it.

A gpg that is there and does not run (`gpg --version` does not exit 0, which is what the
tool asks before every copy) is a miss too, "The gpg program at <path> does not run: <what
it said>.", with "Install gpg again" as its fix.

**systemd in WSL** (c-804) is a row only on Windows' WSL, right after the OS: required,
and off until `/etc/wsl.conf` turns systemd on, its fix the two lines and `wsl --shutdown`
from Windows, with the one command that writes them to copy; on WSL1 its fix is converting
the distro to WSL2 (`prereqs.wsl_check`,
[install](88-install.md), "Windows, through WSL2").

**gpg, for backup** (c-757) is the last row, and the one that is never required: its
label says what it is for, the page adds "(does not block)", and a miss is the quiet form
with its fix and, on a Mac, `brew install gnupg` to copy. Every backup copy is encrypted
with gpg and nothing else needs it, so an install never stops for it
(`prereqs.gpg_check`, [install](88-install.md)); the Back up step refuses to turn on
without it and its line there has **Open Check this computer**, which opens this step.
It is looked for where the backup's jobs look (the fixed PATH the service manager hands
them), so a gpg only the user's own shell can see is a miss that says where it is.

The design draws six rows. The screen has nine on a machine that passes: Python's sqlite3
module, "Claude Code can list its sessions" and gpg are checks of their own (`prereqs.py`),
and a check that can fail is shown rather than folded into its neighbour.

A core step with no entry in `K.startPanels` says so on its screen. Only a pack's own step
(`<pack>:<id>`) is drawn by the pack screen.

Where it replaced what: a machine check's "Fix:" line, the login's line, a pack check's red
badge with its reason as a hover title (Setup and the Where finished work goes step), a pack
step's named check, and every readiness row a step shows. Rows of one space that fail for
ONE reason are one line naming them all ("Tracker, Code host, Review scanning, CI builds"),
so a space with no pack says so once.

**Bosun's session can run** is one rule (`K.bosunSession`), read from readiness's install
rows, for the header line and the third part alike, so the page never points at a session
that cannot answer:

- `builder` is ready: builder mode is on and Start would not refuse;
- `login` is ready: an expired or missing login draws nothing. A login that could not be
  checked (`sure: false`) IS ready here, so a probe that timed out never hides a live
  Bosun, on a finished install least of all;
- `prerequisites` is ready: no required machine check fails (Claude Code is one of them). A
  failing check that does not block changes nothing, so on a signed-in install it still
  ends with Bosun's part.

**The command** is the state's own (`console.attach`, or
`bosun.attach` while no session exists; `deckstate.attach_line`): this install's
`<home>/bin/keel console attach`, not the bare `keel console attach` the design's drawing
shows, because an install's `bin/` is not on the user's PATH unless they put it there. The
path is quoted where a shell would split it, so the line copies as a working command. It
joins Bosun's session from a terminal on this machine, and starts it first when it is down
([Bosun](96-bosun.md), "The user's terminal").

The stepper's verbs, in the same table as Setup's (`actions.SETUP_TABLE`), so they are the
page's alone and take the setup lock, all but `firstrun.seen` (`firstrun.UNLOCKED`, r2.F4):

| Verb | Body | What it does |
|---|---|---|
| `firstrun.skip` | `step` | stores the skip; refused for a required step, for a step with no Skip (Choose your builder) and for a step that does not exist |
| `firstrun.unskip` | `step` | takes the skip off |
| `firstrun.seen` | `step` | the user went on past a step with nothing to check (c-729, `firstrun.seen`): stored as `seen`, so it reads done from then on; refused for a step with a check of its own (`firstrun.checked`, which reads only that step, never the whole report). It takes no setup lock: the page sends it as the next step opens, maybe while an Add repo copy holds the lock, and its one write is serialised by `firstrun.change` (r2.F4) |
| `firstrun.finish` | none | stores Finish; refused while a required step is not done, naming it |
| `firstrun.reopen` | none | clears Finish, so the deck opens Start again |
| `firstrun.backup.on` | `folder` | Back up's one verb (c-678, `backupsetup.turn_on`, [backup](85-backup.md)): the folder as the store in `[backup]`, the tool's `init` for the keys, the hourly snapshot and weekly proof loaded, and the first copy started, never waited for (c-757; `started` in the answer). Its answer carries `passphrase` once, only when this call made the key. Refused on a computer with no gpg where the backup looks (`detail`: `kind` "gpg", `step` "prerequisites"), for a folder inside the install (with the suggested one as `detail`), a folder with files in it while this computer holds no backup key, a store already named, and another install's job already loaded. The config edit also writes `[backup] since`, when the turn-on happened, which is how the step and the drain tell this install's copies from an earlier install's. All or nothing: a failure after the config edit puts the config, the jobs, the folder and a key that call made back as they were. A config verb: the deck reads the config again after it, in place (c-729) |
| `firstrun.browser.install` | none | A browser for sessions' Install and Try again (c-678, `browserinstall.start`): starts `bin/keel-browser install` detached from the deck. Refused while a download is running, and while Node.js is missing or older than 20 |
| `firstrun.login.check` | `space` (optional) | probes the install's login now (`login.check` with `force`), or the named space's (the sign-in banner and a Logins row, c-678; refused for a space that does not exist), and drops the kept readings (`readiness.forget`), so the next state reads everything again |
| `firstrun.identity.save` | `name`, `email` | Check this computer's Save (c-679): writes git's global `user.name` and `user.email`, each only where git has none (`prereqs.save_identity`), and drops the kept readings. Refused once git has both; refused, with nothing written, for a value that is empty, not one line of printable text, or beginning with a dash; and when git refuses the second write the refusal says the first was saved ([install](88-install.md)). The one verb here that writes outside the install: git's own setting, with what the user typed |

## The verbs

Run by `actions.SETUP_VERBS` through `onboarding.VERBS` (and `landpush.VERBS` and
`stuckcards.VERBS` for the verbs of a landing and of a stuck state):

| Verb | Body | What it does |
|---|---|---|
| `setup.repo.clone` | `space`, `key`, `url` | `git clone` into `<key>/repo` (ten minutes at most, no prompt for a password), lists it under `[spaces.<space>.repos]`, writes the space and repo tiers from the templates where absent. A failure leaves nothing behind: no half clone, no folder it made, no config entry |
| `setup.repo.add` | `space`, `url`, `key` (optional) | Add your repos (c-678): the space made when it is not there (as `setup.space.add` makes one), the key filled from the address when none is given (`cloneerrors.short_name`), then the clone of `setup.repo.clone`. A copy that fails puts the config back as it was before the space was made, and its refusal carries the failure's kind as `detail` |
| `setup.repo.attach` | `space`, `key`, `path` | an existing checkout listed under `[spaces.<space>.repos]` where it is (c-632), as `shipyard import` lists them: nothing cloned or moved, and outside the layout the tiers do not load there. The space is made when it is not there, and taken back when the attach is refused (c-678). Refused for a path that is not absolute, holds no `.git`, is a card's worktree, or is inside another install's `spaces/` |
| `setup.space.add` | `space` | a plain `[spaces.<space>]` (c-632), with the install's `config_dir` and no repos, through `configedit.append_table`; refused for a name that exists. While the first run is not finished the table also says `fetch_before_work = true` and `offer_push = true`, and its note reads "Added in the deck's first run"; on a finished install it says neither and the note reads "Added from Setup" (`reposetup.add_space`) |
| `setup.repo.remove` | `space`, `key` | the config entry taken out; the folder and its tier stay. Refused while an open card (not done, not archived) of the space names the key, naming the cards |
| `setup.pack.on` | `pack`, `space` | a new `[spaces.<space>]` from the pack's example, or an existing space with no pack adopted (`packsetup.pack_on`, [packs](62-packs.md)) |
| `setup.pack.off` | `space` | the space's `pack` line, the keys Turn on wrote from the pack's example where they still equal it, and the "Turned on" note taken out (c-688, `packsetup.pack_off`, [packs](62-packs.md)); the space, its repos and its own keys stay. Refused for a space on no pack, for one written by hand as `adapter =` or inline, and while the space has open cards, naming them |
| `setup.pack.build` | `pack` | c-740 r1.F1, `packsetup.build_pack`: a pack cloned into the packs folder listed as the personal repo `pack-<name>` and named in `[builder] repos`, and Bosun's clone of it made; refused where Bosun is not the install's builder, for a pack with no repo of its own, and for a key one of the user's repos has ([packs](62-packs.md), "A pack someone shared") |
| `setup.tier.save` | `space`, `key` (optional), `text` | the space tier, or a cloned repo's tier, written in one rename |
| `setup.tier.propose` | `space`, `key` (optional), `likes` | files the audit card for that tier (below) |
| `setup.tier.adopt` | `card` | writes a proposal at review into its tier, audit notes stripped, then closes the card and stops its house; Approve outcome on the card does the same (`onboarding.adopt_proposal`, below) |
| `setup.tier.draft` | `space`, `key` (optional) | the draft card Bosun works with the user for a tier that has none (c-678, `tiercards.open_draft`): a repo copied in before draft cards, or one whose card was archived. Refused with no builder and for a tier that has an open draft or proposal. A copied repo leaves its card by itself |
| `setup.flow.propose` | `space`, `words` | files the card that writes that space's flow from the user's words (c-640, [flows](64-flows.md)) |
| `setup.flow.draft` | `space` | the card on which Bosun drafts that space's flow with the user (c-678, `flowcards.open_draft`, [flows](64-flows.md)): at `inbox`, with `flow_proposal` and `flow_draft`. Refused for a space that has an open flow proposal |
| `setup.flow.adopt` | `card` | checks the proposal at review once more, writes exactly what it checked as the space's flow, then closes the card and stops its house; Approve outcome on the card does the same |
| `setup.flow.reset` | `space` | the space's own flow set aside (`flow-<stamp>.toml.bak`), so its pack's or Keel's applies |
| `setup.settings.save` | `changes`: a list of `{table, space?, key, value}` | the Settings view's Save (c-633, `keel/settings.py`): every change is checked against the schema first (a known setting, a space that exists, a value it may take, refused by name otherwise and nothing written), then all are written in ONE `setupconfig.edit`, so one backup, and the deck reads the file again in place (a change to voice re-execs it, `deckreload`). A save that touches `[builder] mode` or `[keel] bosun_builder` records or takes out Claude Code's acceptance of bypass mode in Bosun's config dir (`builder.record_bypass`, c-729). A `null` value takes the key out of the file so its default applies. Saving `review_auto` or `review_model` clears the Reviews gear's override of it. A change to `[voice]` also reinstalls the voice gateway when it is loaded (`voice.reload_if_loaded`, `keel voice install --load`), in the same quiet moment as the deck's re-exec (which a voice change still takes), because the gateway reads its environment, not the config |
| `stuck.model` | `id` | the space's default model on a card blocked for naming none (c-678, `stuckcards.set_model`); the page then starts it afresh. Refused on any other card |
| `land.aside` | `id` | a refused landing held by changes never committed in Keel's own copy: they are stashed there, named for the card (`stuckcards.set_aside`); the page then lifts that block and approves again. Refused for a folder the user attached |
| `land.unlock` | `id` | a refused landing held by a stale `index.lock` in Keel's own copy: the file is removed (`stuckcards.unlock`); the page then lifts that block and approves again. Refused while the lock is younger than 30 seconds, since a command may still be running there, and it says to wait |
| `services.restart` | none | the service that runs the drain, restarted (`stuckcards.restart_services`): the manager's real restart for a job it has loaded (hung or crash-looping; a start of a loaded job leaves a running one as it is), a start for one that is installed and stopped. Refused for a job that was never installed, beside another drain of this user, and with what the service manager said |
| `setup.config.remove` | `table`, `key` | an unknown key's line taken out of the config (`stuckcards.remove_key`); refused for a key Keel knows. A config verb |
| `setup.config.rename` | `table`, `key`, `to` | an unknown key's line kept under the name Keel knows (`stuckcards.rename_key`); refused when `to` is not a setting of that table, when the table already has it, or when the value is one the setting may not take. A config verb |
| `land.push` | `id`, `fetch` (optional) | the Push of a done card that landed by a local merge (c-678, `keel/landpush.py`, [flows](64-flows.md)): a plain `git push` of the branch it landed on, never forced; with `fetch`, the remote's commits are fetched and merged in on a tested tree first, by a worker that runs only when shown the event this tap left on the card. Its refusal carries a `detail.kind`: `behind`, `conflict`, `tests` or `failed` |
| `land.push.check` | `space` | "This computer can push to origin": a dry run of the push for each repo the install copied into that space; it changes nothing at the remote |
| `setup.pack.draft` | `space`, `words`, `reviews` (optional, true or not) | Another provider (c-678, `packdraft.draft_connection`): files the card on which the in-app builder drafts a pack for a code host Keel ships no connection for, on `packs`, attended, at `assigned`. Its brief says, from `reviews` (c-730), either to build review requests too, in the GitHub pack's pattern with `review_scan = false` under `[space]` (`packdraft.REVIEWS_YES`), or to leave them out (`REVIEWS_NO`). Refused with no words, with no in-app builder that builds `packs`, and while one such card is open |
| `setup.import` | none | "Import my Claude setup" (c-619): files a card on `packs` for the builder, at assigned, whose brief reads the user's `~/.claude` (CLAUDE.md, skills, agents, commands; its settings and credentials denied by the builder's settings) and writes them as the pack `mine` on its branch; settings, hooks and MCP servers are not imported, and the outcome says so for the user to carry by hand. There is no import code: the brief is the whole of it, and Approve outcome lands it ([Bosun](96-bosun.md), "The builder"). Its panel says so before the tap (a card of its own for Bosun, a draft pack on a branch, nothing changes until Approve outcome on that card), and after it shows the open import card as a link with its state, in place of the button (`report.builder.importing`, `onboarding.open_import`; `K.proposing`, c-664) |

They are the page's alone: a body with a `caller` is refused (as for the house verbs), and
the page's cookie is asked for like any human path ([the deck](40-deck.md)). Each refuses
a config that is not an install's (`setupconfig.install_of`, the `config.toml` of a
directory outside the code), so a checkout's own config (an older checkout's `keel.toml`) is never written from
the deck. After a verb that changed the config (`onboarding.CONFIG_VERBS`) the deck reads
it in place (`deckreload.reload`, c-729), or, for a change to what the process bound at
start, execs itself once nothing it holds would be cut (`serve.schedule_restart`,
`restart.due`: a conversation, a house call or a deck action), and the drain sees the file move between passes and logs "config moved since start"
(`drain.config_moved`, [the drain](30-drain.md)). One setup verb runs at a time
(`serve.SETUP_LOCK`, held until the change is read or, on a restart, until that exec): a second is refused with "another setup change
is running".

## Propose and adopt: the audit

`keel/tiercards.py`. Propose takes the user's own words first: the control has a box, "What do you
like? (style, testing, review, anything)", whose text goes into the card's brief verbatim as
the user's preferences (empty is allowed). It then files a personal errand (no `repo`, so no
worktree) carrying `options.tier_proposal` (`<space>/<key>` for a repo tier, `<space>` for
the space tier) and the clones as `options.add_dirs`, at `assigned` with autonomy
`autonomous`.

The brief asks for an AUDIT, not a summary of the team's file: read the code, its config,
CI, linters and formatters, tests, the commit history and the team's CLAUDE.md and
`.claude`; find the practices the repo actually follows (naming, structure, test commands,
lint and format, branch and commit habits); note where the team's file disagrees with what
the code does; and write the tier from the user's preferences plus the findings, those preferences
winning on a conflict, in the template's pattern, to `state/cards/<id>/claude-md.md`. The
file ends with a `## Audit notes` section, one line per practice with its evidence (a file
path), then stages review with that file as its output. A space-level Propose does the
same over every repo the install cloned into the space, for what they share. The house's
cwd is its card directory, so no CLAUDE.md of a clone is loaded into it. One open proposal
per tier.

**A draft card: the same proposal, drafted by Bosun with the user (c-678).** Copying a repo
in (`setup.repo.add`, `setup.repo.clone`) on an install with a builder leaves a card
`Draft the <space>/<key> CLAUDE.md` in personal for that repo's tier
(`onboarding.leave_draft`, `tiercards.open_draft`): `options.tier_proposal` as above, plus
`options.tier_draft`, at `inbox` and not `assigned`, so the drain starts no house on it. It
is the user's tap that files it, since only the user may make a proposal card. Bosun takes
it in conversation: `building` when it starts, `review` with the draft when it is ready
([Bosun](96-bosun.md), "The setup conversation"). The draft is read from the card's own
directory, else from Bosun's folder for the card (`tiercards.draft_path`), and Adopt is
the one function it always was. A copy with no builder leaves no card; a card that cannot
be filed never fails the copy. Setup's Propose on a tier whose draft card nobody has
started archives that card and files the audit in its place; one Bosun has started holds
the tier like any open proposal. Turn off for a pack does not count a proposal card among
a space's open cards (`packsetup.open_cards`): it has no repo and lands nothing.

**Read-only by mechanism.** The house never gets the clone: propose makes a disposable
`git clone --shared` of each clone under `state/cards/<id>/audit/<key>` (its objects are
the clone's, and the clone gets no worktree entry) and hands those copies over as its
add-dirs. The real clones are listed in `options.tier_reads`, and the house's settings deny
Edit, Write, MultiEdit and NotebookEdit on them (`tiercards.read_only_deny`, through
`house.settings_body`). Adopt removes the copies; nothing removes those of a proposal that
is never adopted, since no hook cleans a card's directory at done.

**What the control says (c-664).** Before the tap, beside the button: Propose files a card
of its own, a Claude session (a house) starts on it when one is free, reads what you wrote
and writes a draft; nothing changes until you Adopt it; and it is a conversation (open the
card, Drop in to type into that session, Send back with what to change, as many rounds as
you like). After the tap the control is the open proposal: its card as a link and its state
in words (waiting for a session to start, working, waiting for you, draft ready; `tiercards.proposals` carries `waiting`, the
card's block), with Adopt once the draft is ready. The words are `K.proposing`'s
(`app/ui.setup.js`), the one helper the flow proposal uses too ([flows](64-flows.md),
"What Propose says"), and they say both ways in: the Adopt button beside the proposal,
or the one on its card.

Adopt, on a proposal at `review`, writes that file into the tier with the Audit notes
section stripped (`tiercards.stripped`), removes the audit copies, and notes it on the card. Adopt is
the user's tap and the card's outcome (`onboarding.adopt_tier`, c-621): the card moves to done as
Approve outcome moves it, and its finished house is stopped (`house.retire_finished`); the
audit card used to sit at review with its house alive. A move the board refuses leaves
the tier written and the answer says why.

**Approve outcome on the card is Adopt (c-667).** Until c-667 Approve outcome on a tier
proposal closed the card WITHOUT writing the tier, so a user who approved on the card
believed the tier was in; a flow proposal's Approve already adopted, but only from the
deck (`kb approve` closed either kind with nothing written). Now there is one function,
`onboarding.adopt_proposal`, and every way in calls it:

| The tap | Where it enters |
|---|---|
| Adopt in Setup (a tier) or in Settings (a flow) | `setup.tier.adopt`, `setup.flow.adopt` (`adopt_tier`, `adopt_flow`: each refuses a card that is not its kind) |
| The card's own outcome button, which reads **Adopt** for a proposal (below) | `actions.act_approve`, for a card `onboarding.proposes` names |
| `kb approve <id> outcome`, as the user | `cli.approve_proposal` |

- **The same checks.** It calls the kind's one writer (`tiercards.adopt`,
  `flowcards.adopt`, the `WRITERS` table); nothing else writes a tier or a flow from a
  card. A draft the writer refuses (no file, an empty one, a flow that does not check, a
  space or a repo that is no longer here, a card not at review) refuses the tap with
  that reason: nothing is written and the card stays at review.
- **Twice writes once, by the draft and not by the stage.** A written draft leaves the user's
  note on its card whose data is `{"adopted": <path>, "digest": <sha256 of the draft>}`.
  A tap is "already adopted" only when the NEWEST note that says adopted is the user's (kind
  `note`, actor `human`) and carries the digest of the draft as it is now
  (`onboarding.adopted_into`): then nothing is written, the move to done is tried again
  if an earlier one was refused, and the answer is "already adopted into <path>; nothing
  was written again", so what you edited in the tier since is kept. A draft revised after
  a refused move has another digest and is written again. When the path the note names
  is gone since (a flow reset, a tier removed), a card still at review is written again;
  a done card says so and asks you to propose again ("<id> was adopted into <path>,
  which is gone since; it is done, so nothing is written again: propose again"). A note
  anyone else left counts for nothing.
- **One tap at a time.** The check, the write and the move run under the card's approve
  lock (`merging.approve_lock`), so two taps cannot both write: the second is refused
  with "another tap is adopting it and is still running".
- **A proposal closes no other way.** A stage move to done is refused for a card carrying
  a proposal option, for every actor, the user's `kb stage <id> done` too
  (`Board._refuse_stage`: "a proposal ... closes by Adopt, which writes its draft; archive
  it to drop it"). So is a `land` relay (`Board._refuse_land`, which is also how Bosun's
  outcome approval lands) and the drain's close of a tracking card
  (`Board.close_tracking`, for a proposal someone split). The remaining closes, a merge
  to done and a decline, start from `shipping`, which a card enters only through an
  Approve outcome that published a pull request or through the shipping sync finding one;
  a proposal has no repo and no branch, and its own Approve never publishes, so it is
  never there. Archive is the way to drop a proposal: it leaves the open proposals
  (`tiercards.proposals`), so another can be proposed.
- **A done proposal that was never adopted** (a tier card approved before c-667) is
  refused by Adopt and by Approve: "its draft as it is now was never adopted, so nothing
  was written. Propose again for a new draft."
- **The user's alone.** `tier_proposal`, like `flow_proposal`, is an option only the user sets, at
  create too (`board.PROPOSAL_OPTIONS`, part of `HIS_AT_CREATE`; the writers' own names
  are held equal to them by a test): a house that put it on its own card would turn the user's
  tap into a write of the rules every session reads. Bosun's approve of a proposal's gate
  is refused by the board (`Board._approve_as_bosun`), and any other actor's by
  `Board.approve`, as for every card. A card naming BOTH proposals is refused whole,
  rather than half adopted. `board.proposals_of` is the one reading of "is this a
  proposal": an option set to nothing is not one.

**What the card says (c-667).** The outcome button of a card carrying a proposal option
(`K.proposalOf`, `app/ui.core.js`) reads **Adopt**, not Done or Approve outcome, on the
card, on the outcome page (`app/ui.plan.js`) and on a kanban drop. Its confirm is "Adopt
<id>? This writes its draft into <the tier or the flow, named>." (`K.adoptConfirm`), and
its tip says what is written and that nothing changes until this tap (`app/ui.tips.js`).
The answer is said as it came (`K.sentence`): "adopted into <path>", "already adopted
...; nothing was written again", or, as an error, "... but <id> was not moved to done:
<why>" when the draft is in and the card still waits at review. Setup's and Settings'
Adopt and the outcome page's send (`sentWord` in `app/ui.plan.js`) say the same answer the
same way, and `K.proposing`'s words name both buttons. A proposal with slices still asks
the Adopt confirm, never the tracking one.

## The config writer

`keel/configedit.py` changes the text of one table and keeps every other byte: comments,
blank lines, key order. A table is a `[name]` header at column 0; it ends at its last key
line (a comment block a blank line parts from it leads into the next table and is not its
own). `set_entry` replaces a key where it is, else adds it after the table's last key, else
adds the table; `append_table` adds a new table after the last of its family
(`[spaces.x]` after the last `[spaces...]`), above any commented-out example table that
follows it; `remove_entry` and `remove_table` take lines out. A table written inline
(`repos = {...}`) is refused: "edit it by hand".

`configedit.write` is the one way an edit reaches disk (`setupconfig.edit`):

1. refused when the file changed since it was read (a hash of the text read);
2. the new text parsed with `tomllib` first;
3. the old file kept as `<dir>/state/config-backups/config.<UTC time>.toml`, the newest ten
   kept;
4. written in one rename, keeping the file's mode (`keel/atomicfile.py`);
5. loaded as Keel loads it (`config.load`), and the old file put back from the backup when
   that fails, with the reason.

`installer.fresh` uses the same writer to take the checkout's own repo out of a new
install's config.

## Files

- `keel/onboarding.py`: the report, clone, attach, remove, add a space and the tiers; the
  verb table.
- `keel/reposetup.py`: what touches git and the config for a repo: the copy, the attach,
  the space, the remove (out of `keel/onboarding.py` in c-678).
- `keel/packdraft.py`: Another provider: the card on which Bosun drafts a connection.
- `keel/firstrunsteps.py`: how each first-run step reads as done (`STATE`), one function a
  step (out of `keel/firstrun.py` in c-678).
- `keel/firstrun.py`: the first run's steps (`STEPS`, `STATE`), the report, `firstrun.json`
  and its verbs.
- `app/ui.start.js`: the stepper, and each step's screen (`K.startPanels`).
- `app/ui.startchecks.js`: the Check this computer screen (`K.checkScreen`), with the form
  for git's name and email; loaded before `ui.start.js` (`app/views.json`).
- `app/ui.signin.js`: the guided sign-in (`K.signIn`), drawn by the step, the banner and
  the Logins list.
- `app/ui.startbosun.js`: Choose your builder and Meet Bosun (`K.builderChoice`,
  `K.meetBosun`).
- `app/ui.startrepos.js`: Add your repos (`K.reposScreen`).
- `app/ui.startmemory.js`: How Keel remembers (`K.memoryScreen`).
- `app/ui.startdrafts.js`: Set up your repos with Bosun (`K.draftsScreen`).
- `app/ui.startlands.js`: Where finished work goes (`K.landsScreen`).
- `app/ui.startships.js`: How work ships (`K.shipsScreen`).
- `app/ui.flowpicture.js`: a flow drawn for a newcomer, one diagram of places and labelled arrows by the board's drawing, and one sentence (`K.flowPicture`, `K.flowSentence`, `K.flowLinesOf`, c-732).
- `app/ui.startbrowser.js`: A browser for sessions (`K.browserScreen`).
- `keel/browserinstall.py`: Node's check, the download, its progress and its failure.
- `app/ui.startbackup.js`: Back up (`K.backupScreen`).
- `app/ui.startcard.js`: Your first card (`K.firstCardScreen`).
- `app/ui.startdone.js`: You are set up (`K.setUpScreen`).
- `app/ui.stuckcard.js`: the stuck states outside setup (`K.stuckCard`, `K.servicesStuck`,
  `K.unknownKeys`).
- `keel/stuckcards.py`: a block read into what happened and its fix, and the fixes.
- `keel/backupsetup.py`: the one verb that turns the backup on.
- `keel/backupstatus.py`: what the Back up step shows, as it is observed, and its verdict.
- `app/ui.landpush.js`: the Push on a card that landed on this computer (`K.pushBlock`).
- `keel/landpush.py`: fetch before work, the push and its check, and the panel of keeping work on this computer.
- `keel/tierdrafts.py`: the rows of what came back, and the step's verdict.
- `keel/repofile.py`: the lines Keel reads out of a repo's CLAUDE.md.
- `keel/repocommands.py`: those lines put to work: the tests, prepare, lands on.
- `keel/tierrecord.py`: which text of a tier the user adopted or saved, the only text whose
  lines run.
- `keel/cloneerrors.py`: a failed copy sorted into a kind, and the short name an address
  suggests.
- `keel/bosunhello.py`: whether the user has said anything in Bosun's session.
- `app/ui.stuck.js`: the stuck line and the line to Bosun's session (`K.stuck`,
  `K.bosunSession`, `K.bosunLine`), and the check row in its four states (`K.check`, c-678:
  waiting, checking, ready, and needs you, which is the stuck line); loaded before Setup and
  the stepper.
- `keel/setupconfig.py`: the install of a config and the checked config write.
- `keel/packsetup.py`: packs on the view, Turn on and Turn off, and which packs are offered.
- `keel/tiercards.py`: propose and adopt.
- `keel/repolayout.py`: the layout, the card's worktree in it, the excludes, the templates.
- `keel/configedit.py`: comment-keeping edits, the backup, the checked write.
- `etc/claude-md/`: the two tier templates.
- `app/ui.setup.js`: the view.
- `keel/settings.py` and `app/ui.settings.js`: the settings schema and the Settings view, whose
  `K.settingsForm({groups, keys, choose, space, onSaved, save})` is the form the first-run
  stepper's How work ships, Choose your builder and Phone and voice steps embed (c-632): the fields of the named groups
  or setting ids for the install or one space, each with its tooltip and info button, and a
  Save over its own fields unless `save` is false. `choose` shows a choice still at its
  default as "choose one" rather than preselected (the voice engine).
- `tests/test_settings.py`, `tests/test_settings_deck.py`: the schema, the loader's warnings,
  the readers, the Save verb, and the view under node.
- `tests/test_configedit.py`: an edit touches only its table, keeps a backup, and is
  refused when the file moved.
- `tests/test_onboarding.py`: a copied repo leaving a draft card that Bosun stages and the
  user adopts from Bosun's card folder, none where there is no builder, Propose taking over
  a draft nobody has started, and the tier a repo starts from carrying the lines Keel reads
  (c-678); Add making the space, copying the repo and naming it
  from its address, a copy that fails leaving no space behind and saying its kind, one in a
  space that was there keeping the space, an address that names no repo refused, a listed
  repo saying its home address and its branch, and Attach making the space too;
  a clone lands in the layout with both tiers and is listed; a
  house on it cuts under `trees/` and carries the exclude; a repo an open card names is not
  removed; the audit reads a copy and may not edit the clone; Approve outcome on a tier
  proposal adopts it, a draft Adopt refuses leaves the card at review, Adopt and Approve
  together write once (a refused move is retried with no second write, a revised draft is
  written again, only the user's note of this draft counts, a second tap while one runs is
  refused), no stage move closes a proposal, a done one never adopted says to propose
  again, a card naming both proposals is refused, and `kb approve` adopts for the user alone
  with the user's words and the house ended (c-667); a tier saves; a pack turned on
  is a space served here on it; a space added is served with no repos; attach lists a
  checkout and refuses one with no `.git` or in another install; Turn on adopts a plain
  space and refuses one on a pack; a demo-only pack is listed on an install only while a
  space is on it, and anywhere else as any pack; Turn off (c-688) takes back every line Turn on wrote (the config text
  compared), lets the next pack bring its own contract and pipeline, keeps a key the user
  changed, leaves a key reformatted by hand in place and names it, takes only the `pack`
  line when the example cannot be read, is not held by a done or an archived card, refuses a space on no pack, one with open cards (naming them), an `adapter =`
  written by hand and an inline table, each with the config unchanged, and is a setup verb
  that changes the config; a pack row says whether it is demo-only; the verbs are refused
  with a caller and on a config that is not an install's.
- `tests/fence.py` `stand_in_probes`: the browser step asks node for its version through
  `browserinstall.probe`, and the fence replaces that name for every test, so a state built
  in any test never runs the real node (`tests/test_fence.py` `StateBuildTest`). Node is
  not on the fence's PATH list, since the deck's fixture tests run the real one.
- `tests/helpers.py` `no_real_tools`: what every first-run test base starts with besides:
  a stand-in for the harness's listing (`harness.agents`).
- `tests/test_firstrun.py`: a report built in a test runs neither node nor the harness; a
  finished install's state reads no step unless Start asks, and one that is not finished
  reads every step; the core steps in the approved order on a fresh install, the
  checks and the login a step each, `bosun` from Meet Bosun on, Choose your builder open
  until a form is picked and read from the config, with no Skip and never sending a
  finished install to Start, Meet Bosun done once Bosun runs and has the user's first
  message, what its screen is told of the form and the workspace, How Keel remembers read
  only with its real paths, Add your repos done once any space has a repo, a skip refused
  for a required step and stored for repos, a clone that
  marks repos done with nothing stored, Finish refused then stored, an existing install
  read as finished, a finished install neither reopened nor rewritten by the new order, a
  config that is not an install's never redirected, the sandbox pack's step after Where
  finished work goes, Your first card, and Check again; `untouched` on a fresh install,
  ended by a skip or a repo and not by a builder mode chosen on step 0; a login that
  could not be checked done and `sure: false`, with Finish on and no redirect after it; a finished install sent to Start again when the
  login expires or a required check fails, its file unchanged; the attach line quoted
  for a path with a space; and the sign-in step's command, `seen` and `stamp`, with Check
  again probing the space it is asked for (c-678).
- `tests/test_start_steps.py`: the screens under node (`tests/fixtures/start-steps.js`, one
  block per screen, on the page `tests/fixtures/start-page.js` builds for both fixtures),
  and every screen file listed in the manifest before the stepper, served, and loaded by
  the fixtures. Sign in to Claude (c-678): the four lines and the one command with Copy,
  the status row waiting, checking, ready and could not tell (quiet, with Check again), the
  one probe the page asks for when a sign-in file appears and once more when it changes,
  none after a probe that could not tell, Common problems and the line about what is next;
  the banner folding the same block under Sign in again and probing its own space; a red
  Claude row of the Logins list drawing it, and any other red row keeping its one-liner.
  Choose your builder (c-678): two cards, neither preselected, each with its five lines,
  Continue waiting for a pick and no Skip, a pick as one save of builder mode and the
  form's mode, and a pick that was not saved with Try again. Meet Bosun: the line for the
  form with Change, the three checks, Start Bosun as `console.start` and the row while it
  starts, Open Bosun's session with the command and the Claude app, the hello row waiting
  and ready, Next waiting for both, the import as a quiet link, a missing workspace in the
  design's sentence with Start again and Copy details and no "or ask Bosun", and a start
  that was refused in the server's words.
  Add your repos (c-678): the space named work and free until a repo is on its way, the
  install's packs repo not counted, the short name filled from the address, an add as one
  verb, the fields cleared after it, a second add waiting its turn and sent once the first
  landed, a ready repo in one line, a copy with no home address as a check that needs you,
  Use a folder I already have, Remove, and a failed copy by its kind: git's line, the https
  address in one tap, Edit the address, what another host needs.
  How Keel remembers (c-678): four layers in order with "then" between, each with where it
  lives, who writes it and who may change it, the real paths, the workspace layer dashed
  with one repo, the lines under the picture, no button but Back, Next and Finish, and
  nothing sent.
  Set up your repos with Bosun (c-678): the hand-over with the command and a first thing
  to say, the form's line, the four things Bosun asks, a row per file with its path and
  its state, a ready row's commands with their lines, Read the draft and Adopt, the text
  read under its path with Tell Bosun what to change and Close, Adopt as
  `setup.tier.adopt` for the card, a row with no card offering one, Skip for now, Next
  waiting for the files, an adopted row with Read the file, Bosun not running at the top
  and on each row with Start Bosun, and the report read again once when the live rows moved.
- `tests/test_tierdrafts.py`: a copied repo as a row that has not started, the state
  following Bosun's moves on the card, the draft's text and the lines read from it, an
  adopted row, the light rows with a stamp that moves with the draft, a row with no card
  given one by the user's tap, the step done once every copied repo's file is adopted, and
  the workspace file: its row and its draft card with the second repo, one card and not
  one per repo, adopted into the space's file, showing no commands, still adopted while a
  new card waits, and not required for the step.
- `tests/test_tierrecord.py`: a file edited after it was saved, or with its test line taken
  out, or emptied, refuses the landing and nothing merges, and the tap, the gate, the brief
  and the state say so; a file never recorded and a held file with no test line land
  untested; the lines are parsed from the one read that was checked; the deny rules against
  several spellings of a path, through a small matcher that says what it cannot prove.
  Also: a saved file runs and a hand edit runs nothing, at the cut
  (with the sentence as a note on the card), in the landing's note and in the brief; a run
  line from a changed file is no run rule; a house's note is no record; Adopt of a draft
  with audit notes, then a cut, runs the adopted prepare; a file from before the record
  runs nothing until Save, and then the saved line runs; the template is no record; a
  house's settings deny its editing tools the space's and the repo's file; the record's
  three standings, a file never adopted or saved saying that and not that it changed, and
  the drafts list telling run, changed and never apart.
- `tests/test_repocommands.py`: a prepare that runs out of time takes the child it started
  with it, and one in a landing stops at the tap's budget and lands nothing; the test command as the config's else the file's, a
  worktree prepared when it is cut and not again, a prepare that fails refusing the cut and
  leaving no worktree, the merged tree prepared before its tests and landing nothing when
  it cannot be, Approve's note and the state naming a landing that runs no tests, and a
  file that names a branch to land on moving nothing and saying so (c-734).
- `tests/test_usualbranch.py` (c-734): Adopt and Save check nothing out; a card naming no
  base is cut from and lands on the remote's default whatever the copy has out, and one
  naming a base still lands on it; the page names the remote's default; a checkout of the
  user's own lands on the branch it has out, and a repo with an integration branch lands
  there and takes no base.
- `tests/test_packdraft.py`: the tap files one attended card on `packs` with the user's
  words and the way to the starting point, needs words, one at a time, a space that is
  there; the report's `connection`; the card is not the user's first card; and `keel new
  pack --into`: where it writes, a pack's alone, never with `--install`, a folder that is
  there.
- `tests/test_stuckcards.py`: each kind's reading (no model, a failed start, red tests, a
  dirty copy of Keel's and a folder of the user's, a stale lock, git's identity, anything
  else, and nothing for a question); the model set only on a card waiting on one, a stash
  in Keel's copy and never in the user's folder, a stale lock removed and a young one left
  with "wait"; each fix refusing a card it is not for, through the page's verb; no verb
  that moves a rewritten branch; with a fake service manager, a loaded drain really
  restarted, a stopped one started, one never installed refused with nothing asked, the
  manager's refusal said, and no second drain beside another; an unknown key read, removed
  and renamed, and a known key refused through the page's verbs.
- `tests/test_stuck_deck.py`, `tests/fixtures/stuck-states.js`: the same on the deck: the
  stuck line with its three parts for each kind, the tap and what follows it, the
  services, the unknown key's two buttons, and the sign-in banner's words.
- `tests/test_firstcard.py`: the last two places and no phone step, the last screen with
  nothing to check, where the phone's rows and a pack that named it point now; a draft
  card is not the user's first card, what the step carries of the card; nothing suggested
  before Adopt, the card Bosun noted once the file is adopted, a note with no reason, no
  note, the brief's line, the parse.
- `tests/test_backupsetup.py`: the suggested folder; a folder inside the install, a path
  that is not whole and a folder that cannot be made are refused with nothing written;
  Turn on names the folder, runs `init` on the new config, loads the two jobs from the
  install's `services/` and returns the passphrase once; a key already there is not shown;
  a failed setup puts the config back; a setup that fails after it made the key, an hourly
  job that will not load, and a weekly one after the hourly loaded each leave nothing (the
  config, the jobs, the folder, the key and its notice card), and a retry starts clean; a
  key that was there before is never taken away; a folder with files and no key is
  refused, and so is one that cannot be listed; another install's job is never replaced,
  hourly or weekly, loaded or installed and booted out, with nothing written first; a job
  file installed before the call is not taken out by a failed one; a passphrase card from
  before the call is left open; one file that cannot be removed keeps neither the key nor
  the refusal; the Finder's file is left; the three checks, with the key, the log and
  since; the step's place and
  state. The tool is a fake executable and the manager a fake with a state per label
  (a folder of installed files and the labels running), so `run_tool`'s own argv and
  environment are what is checked.
- `tests/test_backupfirst.py`: the Back up step as the first teammate met it (c-757), each
  kept as it was reproduced: a turn-on with no gpg refused with nothing written; the first
  copy started by the turn-on; "writing" said only while a run holds the lock; a start that
  cannot be made answered as not started; what happens next said true to the drain; the
  step's verdict in each case (a copy and nothing wrong, a run that failed after a copy, a
  folder gone, a failed proof, a missed one, no copy and a failed first run); the turn-on's
  time in the config, unmoved by `keel backup install`; an install with no key, or one
  that is not a time or is later than now, taking every stamp as its own; a folder with no
  copy listed at most twice over three looks; the real tool recording nothing for a
  mistyped run, a held lock or a signal, keeping a success against a failure after it,
  recording a proof that dies anywhere, keeping a proof that passed against a failure
  after it, writing its record where the lock is refused, and making a record wait for the
  one being written (the test holds the lock); a copy written after a look seen by the
  next one, with nothing forgotten between; `same_disk` from stated devices; a store that is
  not a folder; a run holding the lock read as writing and the step as
  pending; a copy that never started not shown as being written; a run of the real tool
  that dies before publishing (a lock that cannot be made, a gpg that does not run)
  leaving its reason for the step; the proof waiting with its real day, failed with its
  reason, passed, and missed, and never missed for a backup turned on after the due day,
  for a first copy that came after it, or on account of an earlier install's copies in the
  folder; an earlier install's copy, proof and failed run not shown as
  this one's; a folder on the install's own disk.
- `tests/test_browserinstall.py`: Node 20 or newer, an older one and none; waiting, the
  tool run once and ending ready, a download that stopped with what arrived, Try again, no
  second download in flight, a restarted deck finding the download by its pid file, a stale
  pid file naming a live foreign process (no download, cleared, Install not refused), a
  tool that ends at once leaving no file, a pid file whose process is gone, nothing started without
  Node; the download stood in for as the real one runs (c-757: the package, then the
  archive into the temp folder with a line per tenth, then the unpacking), with the percent
  following it, never a number where the log names no size, how far a stopped one was, and
  an archive begun again counting from its start; the step's place and state, the readiness
  row, the verb.
- `tests/test_flowdrafts.py`: the user's tap files a flow draft card that waits for Bosun,
  one per space; nothing is shown with no draft, no flow before review, the draft drawn as
  a flow at review, a draft that does not check says why; the report carries it; Adopt
  writes Bosun's file as the space's flow; the step's `plans` and its heading.
- `tests/test_landpush.py`: a new card builds on what the team pushed, the switch off
  fetches nothing, a fetch that fails or a copy that has moved too never refuses the card,
  a repo outside the layout and a space on a pack are left alone; a landed card offers the
  push until the remote has it; the push, the refusal when the remote is ahead with
  nothing forced, commits that disagree and red tests merging and pushing nothing; the
  worker: the verb marking the card and returning before anything is fetched or tested,
  the worker merging, testing (told the base) and pushing with its answer on the card, red
  tests leaving the refusal on the card, a worker that died not shown as testing for ever,
  a worker nobody tapped for (no tap, another card's, a house's note, the bare command)
  pushing nothing and changing nothing, a tap good for one worker, a card that cannot be
  read ending the worker without a crash, a plain push refused while a worker tests, a pid
  another process took not read as the worker,
  no second worker beside a live one, a plain push staying in the tap with its refusal
  kept, each verb refusing through the page, and a session unable to write the mark; the
  fetch sentence on the card and in the brief, and the fetch's own clock; a space whose
  config names neither switch; the dry-run check; the panel.
- `tests/test_runrule.py`: a copied repo has a run rule only once its file says how, a repo
  outside the layout has none to meet, a card on a repo with no run rule cannot take the
  browser at create, at a set or by being moved there, it can once the file says how, any
  other card is as it was, and the brief's section: tests only, the command, or nothing.
- `tests/test_repofile.py`: each line found by its opening words with its line number, the
  run rule, the template naming nothing, stars and case ignored and the first line
  counting, nothing for no file, and a value held to one line that starts with no dash.
- `tests/test_cloneerrors.py`: each kind from git's own words, the sentence and the line
  shown, the https address of an SSH one, and the short name, host and slug of an address.
- `tests/test_bosunhello.py`: no hello for a Bosun never started; what Keel and the harness
  put in a transcript is not one; the two prompts Keel types, word for word, neither a
  hello (c-731); the user's own message is, found as the file grows and
  once a half written line is whole; a hello in an earlier session still counts; once
  found, no transcript is looked for again; and a transcript that cannot be opened, or a
  folder of sessions that cannot be listed, is hidden, not silent.
- `tests/test_start_deck.py`: the stepper under node (`tests/fixtures/start-deck.js`): the
  boot redirect, Next off on a required step, Skip, the resume, `K.openStep`, the rail and
  More, a needs panel's Set it up; and the frame (c-677): the list's order and states, the
  phone's strip, Next from the step's own state, the header line only from Meet Bosun on
  and only while Bosun's session can run, the three parts of a failing requirement on a
  step and in Setup (Bosun's part drawn, before Meet Bosun and after, for a failing
  optional check on a signed-in install or a login that could not be checked, and not
  with no builder, an expired login, or a required check failing), the done count on More
  leaving out a step that is not confirmed, and a finished install drawn with
  nothing asked and nothing sent; a finished install with open steps paged through with
  Next and Back; a fresh install opening on Choose your builder; the sign-in step for a
  login that could not be checked (the why line, the list word, the quiet status row);
  the quiet form for a check that does not block; every core step
  having its screen; Setup's Turn on asking for a space; Check this computer (c-679): a
  miss named by its label with the check's own sentences and its command with Copy
  (through `K.fixOf`), git's name and email as two fields starting from what git has (one
  it has cannot be typed over), Save sending `firstrun.identity.save` and nothing while a
  field is empty, and the row a passing check once they are set; and a pack's own fix (c-688): the
  sentence, the command with Copy and how you know, in Setup, on the first run's pack row
  and on the readiness row the check holds up (each fix named when two checks hold it
  up), no button for a check's `action`, Turn off for a space the pack is on (a No at the
  confirm sends nothing, and its words, a demo-only pack's for its last space and for one of two among them), and a pack that
  does not load said in the Packs panel, the one line for a shared pack there on an install
  and only there, and a wrongly named folder as a line of its own beside the packs that list
  (c-740).
