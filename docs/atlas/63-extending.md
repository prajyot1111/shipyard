# Extending Shipyard

There are three kinds of extension, and a builder (a person, or Bosun, Shipyard's admin
agent) adds each with one command (c-634):

- a **pack**: an integration with a tracker and a code host ([Packs](62-packs.md));
- a **segment**: an area of life, with a fetcher and tiles on the deck
  ([Segments and fetch](70-segments-and-fetch.md));
- a **deck view**: a page of the deck ([The deck](40-deck.md)).

```sh
keel new pack <name>
keel new pack <name> --kit
keel new segment <name>
keel new view <name>
```

All three live in `keel/scaffold.py`. Each one refuses a name that is not a plain
identifier or is already taken, writes from one template, checks what it wrote with the same
check that holds the shipped ones, removes it again if that check fails, and prints the
files, the next steps and a pointer to this page. It files no card: whoever runs it is
already working inside a card.

## Where it writes

By default the command writes into the checkout it runs from. The extension therefore goes
through a card, review and the pipeline like any other code.

`--install` writes into the install's own tree instead: a pack goes to the install's
`packs/` directory, a segment to the install's `segments_dir`. Those already win over the
checkout's, but nothing reviews them, because they are not in git.

A view is code, so it is only ever the checkout's. `--install` is refused for a view, and it
is refused when the config is not an install's (one made by `shipyard init`).

`keel new pack <name> --into DIR` (c-678, `scaffold.pack_into`) writes the pack into a packs
folder the caller names, and reads no config. It is how the builder drafts a connection for
a user whose code host Keel ships none for (with `--kit`, "A pack on the kit" below): in
its own clone of packs, on its card's branch, so the draft is reviewed and landed like any
other change
([onboarding](89-onboarding.md), "Where finished work goes", the draft choice). `--into` is a
pack's alone, is refused with `--install`, and is refused for a folder that is not there.

## A pack

`keel new pack <name>` copies `packs/sandbox` to `packs/<name>`, skipping `__pycache__` and
keeping the executables' modes. It then rewrites the header comment, `name`, `description`
and the first-run step's title in `pack.toml`, and the `pack = "sandbox"` line in
`config.example.toml`. The sandbox's `demo_only` line (c-688, [packs](62-packs.md)) is left out,
so Setup offers the copy on an install.

The sandbox's `[capabilities]` (tracker, codehost, reviews and routes) come with the
executables behind them. So do its `[terms]` (the space's own nouns, `keel/terms.py`) and
its `[[setup]]` step (a first-run screen, `keel/firstrun.py`). That is why `packs.load` takes
the copy the first time: the scaffold runs it, and removes the copy if it fails (a copy
that fails half way, or a `pack.toml` it cannot rename, is removed too).

The copy's verbs are the sandbox's code, which takes its pack name from the directory it sits
in (`sb_card.ADAPTER`). So a copy serves the spaces that name it, never the sandbox's, and its
brief and fence name its own `pr` and `publish`. Like the sandbox's, they run only inside a
sandbox (`demo/sandbox`, its `.keel-sandbox` marker and its own `keel.toml`) and refuse on any
other install, because their tracker and code host are JSON files on disk. That is the
starting point to replace: the verbs' insides with your tracker's and code host's.
`tests/test_scaffold.py` runs a copy's verbs in a sandbox whose space names it.

The rules that hold a pack:

- A capability is true only while its verbs are present. `packs.load` refuses a claim
  without its executables (`NEEDS` in `keel/packs.py`).
- A pack names the space, not the vendor.
- Vocabulary lives only in the pack (`drift-terms`).

To turn it on, use the deck's Setup view (Integrations), or name it as `pack = "<name>"` in
a `[spaces.<name>]` table. The format is in [Packs](62-packs.md).

### A pack on the kit

`keel new pack <name> --kit` (c-735, `keel/scaffoldkit.py`) writes a code host pack on the pack
kit instead of a copy of the sandbox ([Packs](62-packs.md), "The pack kit"): every verb a shim
over the kit, a host layer whose every operation is a stub that says it is not written yet
(`<stem>_layer.py`), its requirement checks (`<stem>_ready.py`), its guard policy
(`<stem>_fence.py`), its rules, its suite fence, its stand-in hook (`<pack>/tests/standin.py`) and the
conformance file (`<pack>/tests/test_conformance.py`, the three contracts a code host with no review
requests holds). The stem is the name with `-` as `_` (`my-forge` writes `my_forge_layer.py`), and a
name that starts with a digit is refused under `--kit`, since no module may (r2.F3). It loads as written, and
its check holds every contract and fails until the layer and the hook are written:

```sh
keel new pack <name> --kit
keel pack check packs/<name>
```

`keel pack check <dir>` (`keel/packcheck.py`) runs the pack's suite and requires the contracts
its claims call for; a draft is done when it passes. `--kit` goes with `--into` and
`--install` as a plain pack does, and is refused for a segment or a view.

## A segment

`keel new segment <name> [--space <space>]` takes the first configured space when `--space`
is left out. It writes three files under `segments/<name>/`:

- `segment.md`, with the frontmatter `name`, `space` and `cadence: hourly`;
- `fetch.py`, a stdlib script that writes `summary.json` with one tile
  (`{"label": "items", "value": N}`), `notes` and `generated_at`, and never touches the
  network;
- `test_fetch.py`, which runs `fetch.py` in a temporary copy and checks the summary's shape.

```sh
python3 segments/<name>/test_fetch.py
```

The core suite does not run that command. Wiring every segment's own tests into `make test`
is its own card.

The checker is `keel/segmentspec.py`. It holds a segment to these rules:

- `segment.md` exists;
- `name` is the directory's name;
- `space` is a configured space;
- the only keys are `name`, `space`, `cadence`, `card-span` and `logins`;
- `cadence` is `hourly`, `daily` or `none`;
- `card-span` is a whole number from 1 to 4;
- there is something to look at: a `fetch.py`, an `app/index.html` or a `service.json`.

A segment that fails is reported, never skipped. `keel doctor` prints a line
`segment <name>: <problem>`, and the shipped-segments test (`tests/test_segmentspec.py`)
fails. The fetch role still runs it: the space a segment's tools run under is set by its
`worker.md`, which already fails closed, and a typo must not stop a working segment's
updates.

Two rules come from `segments/README.md`: the app never touches the network, and reading is
free but writing outward is not.

## A deck view

`keel new view <key> [--title <Name>]` takes a key of lower case letters and digits, a letter
first. It appends one row to `app/views.json` and writes `app/ui.<key>.js` with a
`K.view<Key>` that draws one panel. The script is inserted just before `ui.js` in the
manifest's `scripts`. No other file is edited.

### The manifest

`app/views.json` is the only list of deck views and deck scripts. It replaced six lists kept
by hand:

- VIEWS and DOCK in `app/ui.core.js`;
- the body switch in `app/ui.js`;
- the script tags in `app/index.html`;
- APP_FILES in `keel/serve.py`;
- the service worker's SHELL, with a CACHE name bumped by hand.

`scripts` is the page's load order. It starts with `ui.core.js` and ends with `ui.js`, the
boot. Each row of `views` has:

| Key | What it says |
|---|---|
| `key`, `name`, `icon` | the route, the label and the glyph |
| `render` | the `K.<render>` function that draws the body, called with `arg` |
| `arg` | optional, handed to `render` |
| `script` | the file that defines `render`; it must be in `scripts` |
| `needs` | the readiness rows the view depends on (`keel/readiness.py`) |
| `dock` | `true` puts it in the phone dock; `when-ready` keeps it out until its needs are met, under More meanwhile |
| `nav` | `false` keeps a row off the rail: More |
| `rail` | `until-finished`: the Start stepper leaves the rail after Finish, and More still lists it. `when-declared` (c-730): listed only while some space declares every capability in its `needs` (readiness rows' `declared`), as Reviews is |

An unmet need makes the page open with a panel saying what is missing and where to set it
up. It never hides the view.

```json
{"key": "demo", "name": "Demo", "icon": "◇", "render": "viewDemo", "script": "ui.demo.js", "needs": []}
```

### What reads it

The server (`keel/deckviews.py`, used by `keel/serve.py`) reads the manifest once per mtime
and checks it. Then it:

- fills the `<!-- keel:views -->` mark in `app/index.html` with the manifest inline as
  `window.KEEL_VIEWS` plus one script tag per entry;
- fills the `var DECK = ...;` line in `app/sw.js` with the scripts and a short hash of the
  manifest, so the worker's cache name changes by itself whenever the manifest does (the
  ETag of the filled `sw.js` covers the file and the manifest);
- serves every listed script: APP_FILES gets them at start, and a script added while the
  deck runs is served at once.

In the page, `app/ui.core.js` takes VIEWS and DOCK from `window.KEEL_VIEWS`. A page that is
not the deck (the plan page, the Console) has none and gets empty lists. `app/ui.js` draws the
body by calling the row's `render` function with its `arg`, and a route no row names draws Now.

A broken manifest is a blank deck, so `deckviews.check` refuses it by name. That includes a
`render` two rows name, and a `render` a script loading before the row's own already assigns
(`deckviews.render_problems`): the later assignment would replace it, and a view keyed `of`
would have replaced `K.viewOf`, which draws every view. `keel new view` refuses such a key
before it writes anything, naming the script or row that has the function. A key is never one
of the routes the deck's core answers itself (`deckviews.RESERVED`: `plan`, `console`, the
retired `prs`), which `tests/test_deckviews.py` holds to every route literal in `app/*.js`.
The copy's example config keeps no `contract` or `pipeline` line: the demo's pipeline
publishes through the sandbox's own `pr`.
`tests/test_deckviews.py` and the node fixture `tests/fixtures/views-deck.js` hold the
shipped one: every row's render defined, the dock, the rail, the dispatch. The page's own
helpers (`K.el`, the morph, `data-key`) are in [The deck](40-deck.md).

## One machine, no machine words

Shipyard runs on one machine, so nothing a user reads or hears names a machine: no "the
box", "the Mac", "the laptop", "the other machine". When a sentence needs a subject at all,
it is "this machine". A new pack, segment or view follows this too.

The guard is `tests/test_machine_words.py`. It reads every string literal in `app/*.js`
(comments stripped) and `keel/**/*.py` (docstrings skipped), plus `etc/house-contract.md`,
`etc/shipyard.example.toml` and every `packs/*/pack.toml`. It keeps a C622 table, empty now
that the two-machine code is gone, and a table entry that matches nothing fails.

The noun rule in `tests/nouns.py` is the same kind of guard. A ticket or change noun (story,
pull request, PR) is said through the space's terms (`keel/terms.py`, and `K.term` and
`K.say` in the deck), never spelled out in core.

## The user, never "he"

Shipyard does not know who its user is, so nothing it says calls them "he", "his" or "him":
a sentence to a house, to Bosun or on the deck, a refusal, a note, a prompt or a brief says
"the user", "you" or "they". A new pack, segment or view follows this too.

The guard is `tests/owner_words.py`, run by `make drift` and so by every `make test`. It reads
what is said, never a comment or a docstring: the string literals of `app/*.js`,
`keel/**/*.py` and `etc/flows/*.toml`, of the guard scripts that refuse a session
(`bin/keel-house-guard`, `bin/keel-builder-guard`, `bin/keel-board-fence`,
`bin/keel-git-gate`, `bin/keel-git-receive`), of the two packs that ship
(`packs/sandbox/`, `packs/github/`) and of the voice service (`voice/harbor_voice/*.py`);
and every line of the shipped text a session or a user
reads as it is (`etc/house-contract.md`, `etc/house-contract-drop.md`,
`etc/pipeline-personal.md`, `etc/space-personal.md`, `etc/space-work.md`,
`etc/shipyard.example.toml`, `etc/claude-md/`, the templates under `templates/`, each
shipped `pack.toml`, `README.md` and `CONTRIBUTING.md`). That list is the whole of it.

Two tables in the module say what is left on purpose, and an entry that matches nothing
fails. `WAITING` holds text a builder may not change: the files under the authority guard
([Bosun](96-bosun.md); the modules that type a prompt into Bosun's session, `PROMPTERS`,
never wait whole, so a prompt there that says "he" fails and only a refusal of theirs waits,
by its own sentence, c-731), one sentence of the board grammar that the talker's memory embeds,
one owner's own rules in the personal space contract, and the voice service's standing
sentences (30 in four files: the dispatcher's notes, the filler's prompt and reasons, the
talker's message, the refine prompt). The voice sentences are read but not yet reworded,
because their wording is proven by the voice selftest, which runs only on the user's
machine; each is its own entry, never a whole file, so a new sentence there fails the
guard and a reworded one drops its entry. `NOT_THE_USER` holds a word that
is not a sentence about the user: a class name, a pattern over what was heard or recorded.
`tests/test_owner_words.py` holds the guard itself, on scratch trees.

## Checks that hold each kind

Each kind of extension, with what checks it and where the check lives.

| Kind | Check | Where |
|---|---|---|
| pack | `packs.load` | `keel/packs.py`, `tests/test_scaffold.py` |
| segment | `segmentspec.check`, `keel doctor` | `keel/segmentspec.py`, `tests/test_segmentspec.py` |
| view | `deckviews.check` | `keel/deckviews.py`, `tests/test_deckviews.py`, `tests/fixtures/views-deck.js` |
| words | machine words, ticket nouns, the user | `tests/test_machine_words.py`, `tests/nouns.py` and `tests/owner_words.py` (both in `make drift`) |
| one install's own names | the public check, strict | `tests/publiccheck.py` (in `make drift`; [start here](00-start-here.md), "The configuration") |
