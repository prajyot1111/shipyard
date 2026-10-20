# Install

`shipyard init <dir>` sets Keel up for one user on one machine, macOS or Linux, in a
directory that user chooses (c-610 step 2, card c-616). `bin/shipyard` is the command;
`bin/keel` is the same CLI and stays as its alias, so `keel init` is the same verb. Keel
is one machine, and an install is that machine's: it has no `[hosts]` table, no `board_url`
and no second machine to reach (a config that still carries them has them ignored with a
warning).

## What init does, in order

1. **Checks the machine** (`keel/prereqs.py`), each line with its fix: the OS (macOS or
   Linux; native Windows is refused, its fix naming WSL2, "Windows" below), on WSL that
   systemd runs it (`prereqs.wsl_check`), Python 3.12 or newer and its `sqlite3`
   module, git and its identity (`prereqs.identity_check`, c-621: `user.name` and
   `user.email`, since a landing commits a merge; its fix is the setup page's two fields),
   the `claude` CLI with its version, and the two harness features Keel is
   built on, `--bg` and `agents --json`, read off `claude --help` and `claude agents --help`
   (no login needed).
   node is checked only when `--with browser` or `--with lavish` asks
   for a feature that needs it, and the line says which. gpg is checked last and is never
   required (c-757, `prereqs.gpg_check`): only the backup needs it, so a miss prints its
   fix and "Not required: setup goes on without it." It is run, not only found: a gpg
   that does not answer `--version` is a miss too. A required miss stops init there,
   before anything is made, all but git's name and email, which the setup page asks for
   ("The checks, and what a miss says", below).
2. **Makes the layout** under `<dir>`: `config.toml`, `state/` (with `logs/` and
   `cards/`), `segments/`, `claude/`, `services/`, `bin/`. A directory inside the code
   checkout is refused.
3. **Writes `config.toml`** from `etc/shipyard.example.toml` with the `[machine]` table
   filled: `state_dir`, `segments_dir` and `fetch_lock_dir` under `<dir>`, a free deck port
   from 8800 up (or `--port`, refused when taken or reserved for another deck), free `lavish_port` and `voice_port`, `host` a slug of the
   hostname (on macOS the LocalHostName, since `hostname` can be an address; a name of only
   digits becomes `shipyard` on every system, c-634), and every space's `config_dir` set to `<dir>/claude`. Only keys the example
   carries are filled, so a key renamed there fails init by name. The example serves only
   the personal space: a pack's space (ours is `work`) stays commented out until its pack
   is imported, so a new install needs no tracker or worktree tools. **A fresh install
   lists no repos** (c-618): the example's `keel = "."` (the checkout Keel ships in) is left
   out, and so are its `keel` entries in `[tests]`, `[house_tests]`, `[integration]`, `[retests]` and `[deploy_tests]` (the tables
   stay, empty with their comments, c-621)
   (`installer.fresh`), and the user adds their repos, and turns a pack on, in the deck: it
   opens on Start, the first-run stepper, until they press Finish
   ([onboarding](89-onboarding.md), "The first run"). The example leaves `[voice]
   engine_default` out, so the stepper's Phone and voice step asks for the voice engine rather than
   picking one (google until they choose).
4. **Writes the wrappers** `<dir>/bin/shipyard` and `<dir>/bin/keel`: they export
   `KEEL_CONFIG=<dir>/config.toml` and `KEEL_HOME=<the checkout>`, unset the variables
   another Keel in the shell may carry (`KEEL_LIVE_STATE`, `KEEL_CARD`, `KEEL_BOSUN`), and run the checkout's own command. init clears the same
   variables for its own process (`installer.FOREIGN_ENV`).
5. **Creates the board** empty (`state/board.db`).
6. **The builder's three things** (`Init.builder`, c-619): the install's key,
   `<dir>/credentials/house-key` (0600 in a 0700 directory; Bosun's key is derived from it,
   `housetier.shared_path` on an install); `<dir>/packs` made a git repo on `main` with what
   is there as its first commit (as Shipyard when git has no name, no email, or neither) and
   listed as the personal repo `packs`; each of the install's own repos
   (`builder.own_repos`: packs, `<dir>/memory` once it is a git repo, c-722 r1.F1, and each
   pack that is its own clone in the packs folder, as `pack-<name>`, c-740,
   [packs](62-packs.md), "A pack someone shared"; the packs repo is made to ignore those)
   listed as a personal repo by `builder.list_own`, and, when that listing is new, added to
   `[builder] repos` (one the user took out is not put back); and Bosun's own clone of each,
   `<dir>/builder/packs` and `<dir>/builder/memory`, and of every other repo
   `[builder] repos` lists that has a live checkout here (`builder.ensure_clones`, full clones
   with `--no-hardlinks`; a repo listed later is cloned by Bosun's next Start), under its cwd
   `<dir>/builder/` ([Bosun](96-bosun.md), "The builder"). Each is kept when it is there. An
   install has one builder, in auto mode unless `[builder] mode = "bypass"`; `[builder]
   superuser = true` is refused on it. The new config names no `mode`: the first run's
   Choose your builder writes it by the user's pick (c-678, [Bosun](96-bosun.md)).
   **The memory** (`installer.memory_line`, c-722, run just before the builder's step so a
   memory repo it seeds is listed there): `<dir>/memory/bosun`,
   `<dir>/memory/talker` and `<dir>/identity`, each copied from `templates/` when the
   install has none, `<dir>/memory` committed as a git repo on `main` (the same commit as
   packs, `memoryroot.commit`), and never written again. A part the checkout still carries
   is not seeded, and the `Memory:` line says it is read from the checkout until
   `shipyard move-personal` (below) brings it in ([Bosun](96-bosun.md), "Where the memory
   lives").
7. **Trusts** `<dir>`, its `state/` and the checkout in the install's own `.claude.json`
   (`keel/trust.py`), so the first house and Bosun start without a trust prompt.
8. **The login.** It says plainly that this is a NEW setup with its own Claude login in
   `<dir>/claude`, that the user's own `~/.claude` is not read or changed, and that anything
   they want from it can be imported later by asking their Bosun. Its answer is what the
   first run's Sign in to Claude step reads (readiness `login`). A one-word `claude -p`
   under that dir (`login.probe`) says whether it is logged in; if not, it prints the exact
   `CLAUDE_CONFIG_DIR=<dir>/claude claude /login`. Logging in is the user's step: it is
   interactive.
9. **Installs the services** (below), or prints them with `--dry-run-services`, or skips
   them with `--no-services` and prints how to run `serve`, `drain` and `fetch` by hand.
10. **Runs the doctor** in its install mode and prints the deck's URL, opening it when
   the services were installed and there is a desk to open it on (`open` on macOS,
   `xdg-open` under a display).

## The checks, and what a miss says (c-679)

The repo's `README.md` carries the install command, `bin/shipyard init <dir>` from a
checkout, and what it needs. There is no one-line download yet: the code is the checkout.

`keel/prereqs.py` is the one place that knows what the machine needs, and it is read twice:
by init, once, and by the deck's Check this computer step every time that page is read
([onboarding](89-onboarding.md)). So that the two say one sentence, every check carries its
words as data, `{name, label, ok, said, what, fix, command, required}`:

| Field | What it is |
|---|---|
| `name` | the check's key, which never changes (`git identity`, `claude --bg (background sessions)`); readiness and the doctor read it |
| `label` | how a person reads it: "Operating system", "Python 3.12 or newer", "Python's sqlite3 module", "git", "Your name and email for git", "Claude Code", "Claude Code can run sessions in the background", "Claude Code can list its sessions", and "Node.js, for <the features that asked>" when `--with` asks for one |
| `said` | what was found: a version and a path, or "not on PATH" |
| `what` | part one of a miss: what happened and why Keel needs the thing, as sentences |
| `fix`, `command` | part two: what to do, as a sentence, and the one command that does it, to copy. `command` is "" where no single command does it: another operating system, or a Linux package manager Keel cannot name (the Homebrew and Xcode commands are given on macOS only, `prereqs.mac_only`), and git's name and email (below). Claude Code's command is its native installer (`prereqs.CLAUDE_INSTALL`, c-729), which needs no root; its fix says how to put `~/.local/bin` on PATH (`CLAUDE_FIX`), and names npm's global install only where npm is, as the fallback for a user with root (`CLAUDE_NPM`), since it fails with EACCES for anyone else |
| `required` | part three: whether setup stops on it |

A check that passes carries no `what`, `fix` or `command`. `prereqs.line` is init's form:

```
  ok   git: git version 2.50.1 (/usr/bin/git)
  MISS Your name and email for git: user.name and user.email not set
       What happened: Git on this computer has no name and email set. When work lands, git records who merged it.
       The fix: Type them into the two fields on the setup page's Check this computer step, and press Save.
       Required, and the install goes on: the setup page asks for it on Check this computer (two fields and Save).
  MISS Claude Code can run sessions in the background: missing from --help
       What happened: Claude Code on this computer is too old to run sessions in the background. Shipyard starts every session that way.
       The fix: Update Claude Code.
           claude update
       Required: setup stops until this is fixed.
```

and after a miss it stops on, init ends "Stopped: 1 thing to fix first. Do the fix above,
then run this command again."

Two more forms of the same words, so nothing says a miss its own way (review F2):
`prereqs.miss_words` is a miss in one line, its label and what happened ("Your name and
email for git: Git on this computer has no email set. When work lands, git records who
merged it"), which readiness's `prerequisites` row says (so the step's why line reads as
its row does) and both of the doctor's git identity lines say; `prereqs.fix_words` is the
fix as one sentence with its command, which the doctor's problem line ends with.

A harness feature whose help did not come back (a timeout) reads "could not be checked",
with "Check again. If it keeps happening, update Claude Code." as its fix and no command:
it is not said as a Claude Code that is too old.

**No check prints a name or an email to paste.** The identity check has no `command`: a
`git config` line with a placeholder name and email, pasted as it is, would pass the check
as a real identity. Its fix names the setup page instead, in init's line and the doctor's.

**git's name and email are required and do not stop init** (c-679). The identity check
carries `page: true`, the mark of a check the setup page fixes itself, and
`prereqs.blocking` (what init stops on) is every required miss without that mark. Init
goes on because nothing it does needs the identity: its one commit is the packs repo's
first (`installer.packs_repo`), made as Shipyard when git has no name or no email, and
its clones need none. So the fields are reachable on a first install. The check stays
required everywhere else: `prereqs.missing` still lists it, so readiness's `prerequisites`
row is not ready, the page's Next is off until it is saved, and the doctor names it.

The identity check also carries `values` (`{name, email}`, what git has for each), and
`prereqs.save_identity(name, email)` is the deck's two fields on Check this computer,
through `firstrun.identity.save`. It is the only write in the module and init never calls
it. Its rules are held there, on the server, whatever a page sends:

- It reads the identity first and writes, with `git config --global`, only the one git
  lacks. A name or an email git already has is never rewritten (a set name survives a Save
  carrying another), and a Save once git has both is refused: "git already has a name and
  email".
- A value that is empty, is not one line of printable text (`str.isprintable`), or begins
  with a dash is refused before git is asked, and nothing is written. The dash rule is a
  guard, not a fix for something seen: git 2.54 stores `--unset` as the literal value
  (probed against a temp global file), and no value is handed to a git that might read it
  as an option.
- The two writes are one after the other and the first is not taken back. When git refuses
  the second, the error says so: "git could not save your email: <git's reason>. Your name
  was saved."
- A key is set, not set, or not read, and the three are told apart: not set is git's exit 1
  for a key it does not have; not read is git not answering (a timeout, an error starting
  it) or answering with anything else. A read that failed says nothing about what git has,
  so the check then reads "could not be checked" (with `unread`, the fields nobody could
  read, and without `page`, so the page offers no fields and init stops on it like any
  other required miss), and a Save is refused with nothing written: "git's settings could
  not be read just now, so nothing was saved; try again".

## Windows, through WSL2 (c-804)

Windows is supported through WSL2, Ubuntu with systemd, where Keel is Linux: systemd user
units, the Linux paths, nothing of its own. Native Windows is not attempted
(`prereqs.os_check` refuses it and its fix names WSL2; `service.REFUSAL` says the same).

1. Install WSL2 with Ubuntu (`wsl --install -d Ubuntu` in PowerShell).
2. Turn systemd on: `/etc/wsl.conf` gets `[boot]` and `systemd=true`, then `wsl --shutdown`
   from Windows and the terminal opened again.
3. Follow the Linux steps inside Ubuntu: `bin/shipyard init <dir>` from a checkout.

The deck is reached from Windows' browser at the same localhost URL init prints: WSL2
forwards a port bound to 127.0.0.1 inside it to Windows' own localhost.

What Keel does about it, all keyed on `service.wsl_version` (WSL sets `WSL_DISTRO_NAME`, and
its kernel names Microsoft in `/proc/version`: WSL2's `...-microsoft-standard-WSL2`, WSL1's
`4.4.0-19041-Microsoft`); `service.on_wsl` is either version:

- **The check.** `prereqs.wsl_check`, asked on Linux's WSL only (it answers None anywhere
  else, so `gather` and the doctor agree), right after the OS. It
  passes when systemd runs the machine (`service.systemd_booted`: `/run/systemd/system`
  exists, what `sd_booted(3)` reads). Off, it is a required miss, since no unit can start:

  ```
    MISS systemd in WSL: off
         What happened: This is Windows' WSL with systemd off, so systemctl --user cannot run and Shipyard's services cannot start.
         The fix: Add the two lines [boot] and systemd=true to /etc/wsl.conf (if it already has a [boot] section, add systemd=true under it instead), then run wsl --shutdown from Windows and open this terminal again.
             printf '\n[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf
         Required: setup stops until this is fixed.
  ```

  The command starts with a newline, so a file that does not end in one keeps its last line
  whole. On WSL1, which has no systemd, the same row is a required miss whose fix converts
  the distro (`wsl -l -v` names it, `wsl --set-version <distro> 2` from Windows), with no
  command to copy, since it runs in Windows, not in this terminal.

  The same check is a row of Check this computer ([onboarding](89-onboarding.md)) and the
  doctor's `wsl systemd` line, whose miss is a problem in the check's own words and fix.
- **The browser.** Init opens the deck with `wslview`, else `explorer.exe`, rather than
  `xdg-open` (`installer.open_url`), so it opens in Windows' browser.

WSL can stop its machine a while after the last Windows terminal into it closes, and every
Keel service stops with it: lingering keeps a user's units across a logout inside Linux, not
across WSL shutting down.

## Bringing an existing Keel in

A fresh install starts empty. An existing Keel (the board, card directories, segments and
the config choices of an older Keel, which may have run on two machines) comes in once,
from a `keel` snapshot, with `<dir>/bin/shipyard import
<snapshot>` ([import](87-import.md)); it refuses an install that already has cards.

## Moving your own things into the install

`shipyard move-personal` (`keel/movepersonal.py`, c-722) is a one-time copy, for an install
whose owner's things were kept in the code checkout before every reader learned to prefer
the install. Run it from the install, `<dir>/bin/shipyard move-personal [--dry-run]
[--checkout DIR]`; the checkout is the code the install runs unless named. It copies:

| What | From the checkout | Into the install |
|---|---|---|
| the work pack | `<checkout>/packs/work` | `<dir>/packs/work`, committed in the packs repo |
| five segments (`movepersonal.SEGMENTS`) | `segments/<name>` | `segments_dir/<name>` |
| Bosun's and the talker's memory | `bosun/memory`, `<checkout>/talker/memory` | `<dir>/memory/bosun`, `<dir>/memory/talker`, committed in the memory repo |
| the identity profile | `<checkout>/identity/` | `<dir>/identity/` |
| the old config, whole (`keel.toml` in `movepersonal.HISTORY`, c-725) | `<checkout>/keel.toml` | `<dir>/history/keel.toml`: only some of its settings are carried, so the file itself is kept |
| the talker's skill links (`movepersonal.TALKER_SKILLS`, c-725) | the links under the talker config dir's `skills/` | their names and targets in `<dir>/memory/talker/skills.json` (`memoryroot.SKILLS`), committed, never over a record there; `keel talker install`, and every talker start, make them again (`talkerdirs.link_skills`), never over an entry there |
| the talker's rulebook (`movepersonal.TALKER_RULEBOOK`, landing B) | the talker config dir's `CLAUDE.md` | `<dir>/memory/talker/CLAUDE.md`, committed in the memory repo; `keel talker install` links the config dir's `CLAUDE.md` to it |
| a space file the tree no longer carries (`movepersonal.space_files`, landing B) | a space's `contract` or `pipeline` that names a file under a moved item (the work pack's pipeline, by its old `<checkout>/adapters/work/` name too), or a contract the checkout changed from the shipped one (one owner's own rules) | the key pointed at the install's copy, a `point` line; a changed contract is first copied to `<dir>/spaces/<space>/`. A key that names an absolute or home path is the install's own and is left |
| the history docs (`movepersonal.HISTORY`) | design docs under `docs/`, Atlas pages 90 to 94, the live run notes under `tests/` | `<dir>/history/<same path>` |
| settings the install's config lacks (`movepersonal.wanted`) | `keel.toml`'s `[voice]`, `[models]`, `[recurring.*]`, the suites' tables and the example's `[keel]` switches; and `[backup] extra` alone of its `[backup]`, from the sets it wrote (`[backup] sets`, else its `[hosts.*] backup_sets`) less keel and code (`movepersonal.extra_sets`): the install's own sets, store and pull are never touched; never a machine key (the install's `[machine]` has its own) or a suite or branch for a repo the install does not list (`movepersonal.left_out`) | `<dir>/config.toml`, one checked, backed-up write (`setupconfig.edit`) |
| the memory repo listed (`Move.list_repos`, r1.F1) | none: the move made `<dir>/memory` a repo | `[spaces.personal.repos] memory` and `[builder] repos`, by `builder.list_own` as init lists packs, a `list` line; the builder's clone is made by the next `shipyard init` or by Start on the first card for it |

A file an install repo once held and removed since (in `git log` of that repo) counts as
held, and is never brought back (`movepersonal.held`, c-725), the talker's skills record
among them (`movepersonal.skills_held`, r3.F7). The checkout is compared with the code the
move runs from (`config.package_root`, `Move.code`), never with `cfg.root`, which follows
`KEEL_HOME`: every Keel service sets that to the live checkout, so a move started from one
would compare the checkout with itself (r3.F3). A real run that would copy and point
nothing, while the install still lacks something a move should bring (from the named
checkout, from the checkout `KEEL_HOME` names, or, run from the code itself, the talker's
rulebook), is refused, naming `--checkout` and what is lacking (`Move.idle`, r1.F10,
r3.F6); a dry run is never refused and says that a real one would be. The deploy asks the
same question before it lets a tree go live (`movepersonal.pending`, [the
drain](30-drain.md), "the preflight"), and the command it names sets both `KEEL_CONFIG`
and `KEEL_HOME` (`deploypreflight.move_command`).

It copies and never deletes. The tree no longer carries these things (c-722 landing B), so
a move run after that deploy reads an older checkout, named with `--checkout`: the live
checkout before the deploy (run with the new code: `<new checkout>/bin/shipyard
move-personal --checkout <live checkout>`), or a worktree of the commit before it. Pointing a
space file is the one change it makes to a setting the install already has, since left alone
the key would name a file the tree no longer carries. It never writes over the install: a file already there is a `skip` line,
a setting the config already has a `keep` line. Every file is a `copy` or `skip` line under
its item, and `--dry-run` prints the same and writes nothing. The files read are the ones
git shows (tracked, and untracked but not ignored), so the talker's uncommitted memory comes
along and a segment's ignored `data/` does not. Running it again copies nothing. It commits before it writes the settings, and only the files it owns: copied this run, or placed by an earlier run and still byte for byte its source (`movepersonal.unchanged`, fix check 3). So a refused settings write leaves the copies committed, a rerun commits what an earlier run left, and the talker's own writes, or an edit by hand to a moved file, stay out of the commit for the user to review. After it,
the doctor's `memory` lines name the install for every part.

## Where the code is, and why `KEEL_CONFIG` and not `KEEL_HOME`

The checkout `shipyard init` runs from IS the code; `<dir>` holds only what is this user's
and this machine's. A git clone inside `<dir>` was the other choice, and was rejected: it
duplicates the code and its updates for nothing.

The install is reached by `KEEL_CONFIG=<dir>/config.toml`, while `KEEL_HOME` stays the
checkout. The config's `root` is the code everywhere: `bin/keel` in a service's command,
`etc/house-bin` on a house's PATH, the space contracts and the adapters all resolve against
it, so a `KEEL_HOME` naming a bare `<dir>` would break each of them. A named toml is taken
at its word (no scratch redirect, `config.state_paths`), and houses, hooks and `kb`
children already inherit `KEEL_CONFIG` (`house.named_toml`): the demo sandbox has run this
way since it was built. The voice gateway's service file carries it too since c-711
(`keel voice install --load` run with the install's config, or a save of a voice setting;
[talker and voice](50-talker-and-voice.md), "Which config it reads"). This refines step 1's "home": `<home>/config.toml` is still what a
checkout with no `KEEL_CONFIG` reads; an install made by init names its own.

## Re-running

init is safe to run again on the same `<dir>`, and that is how an install is repaired: an
existing `config.toml` is kept and said to be kept, an existing board is kept, and what is
missing (a directory, the board, a wrapper, a trust entry) is made. The wrappers are
rewritten when they differ, so running a newer checkout's init points the install at it.

## Services: `shipyard service`

`keel/appservices.py` defines the install's three services and
`shipyard service install|start|stop|status|uninstall [deck|drain|fetch] [--dry-run]` drives them:

| Service | Runs | Label |
|---|---|---|
| deck | `keel run --roles serve` on the install's `serve_port` | `dev.shipyard.deck` |
| drain | `keel run --roles drain` | `dev.shipyard.drain` |
| fetch | `keel run --roles fetch`: the segments' fetchers, their asks, the recurring cards ([segments](70-segments-and-fetch.md)) | `dev.shipyard.fetch` |

All three run as the user, with the install's `KEEL_CONFIG`, the checkout as `KEEL_HOME`, the
Python init ran with, a PATH led by the folder `claude` was found in on init's shell (nvm and
npm installs live outside the fixed folders), and logs in `state/logs/deck.*.log`,
`drain.*.log` and `fetch.*.log`. The deck and the drain keep
`KillMode=process` on Linux for the engine's reason ([the drain](30-drain.md): a house's
daemon lives in the unit's cgroup); the fetch role starts no house, so its unit keeps
systemd's default and a stop ends the fetcher it was running with it
(`appservices.HOUSE_STARTERS`). The units are rendered into `<dir>/services/` and copied
where the manager looks.

**The fetch role is a service of its own** (c-742). The first installs ran only the deck
and the drain: the old engine's one process ran `drain,serve,fetch` (`keel/install.py`), and
the fetch role was left out when that became two services. Nothing ran a fetcher, so a
segment never wrote its `summary.json`, the Segments page said "No segment is installed"
over a segments folder that held five, no ask became a card and no recurring card was
filed. It is its own process, not a role of the drain's, so a fetcher that takes ten
minutes or fails never holds up a pass of the drain, and each restarts alone.

**`install` touches only what needs it** (`appservices.current`): a service whose installed
unit is byte for byte the one it would write, and which is running, prints "already
installed and running as pid N, left running" and is not restarted; one that is missing,
changed (a newer checkout, another PATH) or not running is written and (re)started. Running
means the manager reports a pid: loaded alone is not enough (r1.F4), since on systemd a
stopped unit stays enabled and reads as loaded, and `install` is the command the doctor
names for a fetch role that is not running. So `shipyard service
install` on an install made before the fetch service adds it and restarts nothing else, and
`shipyard service install fetch` names it alone.

**An existing install gets a new service at its next deploy, with no hand step**
(`appservices.bring_up`, called by `appservices.upkeep` once as the drain starts). A
deploy moves the checkout and every Keel process restarts itself onto the new code; the
deploy worker restarts nothing and runs the old code besides, so it cannot be the one to
add a service. The drain is: on the new code, as it starts, it installs and starts each
service the install never had (`appservices.missing`), and logs
`service dev.shipyard.fetch was missing: installed and started`, once the manager reports
a process for it and not before ("Started means it is running", below). Four guards keep
that narrow.

- **Only a service added since installs were first made** (`appservices.ADDED_LATER`: the
  fetch role). Never the deck or the drain: one of those missing was taken down, or never
  wanted, by its owner.
- **Only one the install never had, never one its owner uninstalled** (review r1.F1). A
  drain start is not rare: every deploy, every config save from the deck and every packs
  move is one, so a drain that reinstalled whatever is absent would fight an owner who ran
  `shipyard service uninstall fetch`. The record is the install's own `<dir>/services/`
  folder: `install` (and this bring-up) renders the unit there, and `uninstall` removes
  only the copy the manager reads and keeps that one. So a rendered unit means "this
  install had it", and the drain leaves it alone; an install made before c-742 has none for
  the fetch role, and gets it once. To have the drain bring it up again, delete
  `<dir>/services/dev.shipyard.fetch.*`; to bring it back yourself, `shipyard service
  install fetch`.
- **Only while the drain's own unit is installed and names this install's config**, so an
  install that runs by hand (`--no-services`) gets no service, and neither does one whose
  labels another install holds.
- **It never rewrites, stops or restarts a unit that exists**: a stopped service stays
  stopped, and a changed unit waits for `shipyard service install`. The one start it makes
  of an installed service is of one its own bring-up loaded and never saw run (c-747,
  below).

**A fetch role already running by hand holds the service back** (r1.F3,
`appservices.fetch_held`): an owner who worked around the missing service with `shipyard
fetch` would otherwise get a second loop at the next deploy. The bring-up then logs
`service dev.shipyard.fetch not brought up: the fetch role already runs for this install as
pid N ...` and tries again at the next drain start; `shipyard service install` and `start`
refuse the fetch service with the same sentence and exit 1, the other services unaffected
([segments](70-segments-and-fetch.md), "One fetch role per install").

**A bring-up that fails says so, and is tried again at the next drain start** (r1.F2). The
real failures return a code and raise nothing (launchd's "Bootstrap failed: 5", systemd
with no user bus), after the unit was copied where the manager looks. Left there it would
read as a service the install has and never be tried again. So the bring-up is taken back
(`appservices.forget`: the manager's own uninstall, then both copies, also when that uninstall itself raises, r2.F2), and
`upkeep` hands the drain's failed step one line, `service dev.shipyard.fetch was missing
and could not be installed and started (exit 5); the next drain start tries again`, which
is in `drain.log` under `service upkeep failed:` and is a sighting. Once per start, never
per pass.

**"Started" means it is running** (c-747). At the c-742 deploy on 2026-10-11 the drain's
bring-up bootstrapped `dev.shipyard.fetch` and logged "installed and started", and launchd
had only loaded it: `launchctl print` said `state = not running`, `runs = 0`, `pended
nondemand spawn = speculative`, `last exit code = (never exited)`, though the plist has
RunAtLoad and KeepAlive. No process, no log, and the Segments page said "not fetched yet"
until `launchctl kickstart` started it by hand, at once. On launchd a bootstrap is not a
start, and Keel said "started" without looking. Three things changed.

- **A load on macOS ends with a real start** (`service.Manager.load`): after the
  bootstrap, `launchctl kickstart gui/<uid>/<label>`, with no `-k`, so a service that is
  already running is left as it is. Every service loaded through `keel/service.py` gets
  it (the deck, the drain, the fetch role, the engine, the talker, the voice gateway); a
  scheduled job (the backup's two) does not, since it runs on its schedule and not at
  every install. `service.Manager.start` does the same: it bootstraps a label that is not
  loaded (a stop is a bootout) and kickstarts either way, so a start of a label that is
  loaded with no process now starts it, where it used to be launchd's complaint. A
  scheduled job is never kickstarted by a start either, loaded or not (r1.F2). Linux is
  unchanged: `systemctl --user restart` (a load) and `start` are real starts already.
  **The pid decides, not the kickstart's exit code** (r1.F1, `service.Manager.kick`).
  Observed on the owner's Mac on 2026-10-11 (macOS, launchd): `launchctl kickstart
  gui/501/dev.shipyard.fetch`, no `-k`, on a label already running as pid 11114 printed
  nothing and exited 0, and the pid and `runs = 1` were unchanged. So a kickstart of a
  running service is a quiet no-op there. Even so, should one ever complain, the state is
  read after it and a label that has a process is a good load and an ok start: a
  non-zero load is what makes the bring-up take a service back out
  (`appservices.forget`, a bootout), and that must never happen to one that runs. A
  kickstart that complains with no process is the load's failure, as before.
- **"Started" is said only after a process is seen** (`service.Manager.running`,
  `appservices.settled`): `shipyard service install`, `shipyard service start` and the
  bring-up look for the service's pid up to 25 times, 0.2 seconds apart (5 seconds,
  `service.START_TRIES` and `START_WAIT`; the pause is handed in, so no test waits). With
  one they print `dev.shipyard.fetch: started, running as pid N`. With none they print
  `dev.shipyard.fetch: not running: launchd loaded it and no process was running after 5
  seconds (<its error log> may say why); `shipyard service start fetch` tries again` and
  exit 1. "Was running after", not "started within": a process that started and died in
  those seconds reads the same from here (r1.F5).
- **The drain's log is true, and the next drain start tries again**. A service the
  bring-up loaded that has no process is a failed step: `service dev.shipyard.fetch was
  missing and is installed, but not started: ...; the next drain start starts it`, under
  `service upkeep failed:`, and a sighting. It is NOT taken back: the unit is installed and
  loaded, and a note is left beside its rendered copy, `<dir>/services/dev.shipyard.fetch.unstarted`
  (`appservices.pending`). At the next drain start `appservices.start_loaded` reads the
  note and STARTS the service (`Manager.start`, never a reinstall), logging `service
  dev.shipyard.fetch was loaded and not running: started` once a process is seen, or the
  failed step again. A service that runs by then (launchd ran it after all, or a login did)
  is left alone and the note removed.
- **The owed start is made at three drain starts, then given up** (r1.F5,
  `appservices.OWED_STARTS`, `gave_no_process`). The bring-up runs before the drain's
  first pass, and a drain start is every deploy, every config save and every packs move,
  so a service that never holds a process (it crashes as it starts) would cost each one
  the whole 5 seconds and a failed step, without end. The note's first word is the count
  of drain starts that have tried. The first two failures end `the next drain start tries
  again (N of 3)`; the third says `service dev.shipyard.fetch is loaded and had no process
  at 3 drain starts: ...; the drain stops trying: `shipyard service start fetch` starts
  it`, once, and drops the note. The service stays installed and loaded; `status` and the
  doctor go on naming it as not running.

The note is what keeps this from fighting an owner's stop. "Loaded with no process" reads
the same on systemd for a service the owner stopped (the unit stays enabled), so the state
alone cannot be the trigger. Only the bring-up writes the note, and a `shipyard service`
verb that has the manager act on that service removes it (`appservices.in_hand`): after a
`stop`, an `uninstall`, a `start` or an `install` by hand the drain starts nothing. A verb
that was REFUSED asked the manager for nothing and leaves the note (r1.F3): a `start` or an
`install` of the fetch service refused beside a fetch role run by hand does not cancel the
start the drain owes, which it makes once that role is gone.

**Decision: the note is a file beside the rendered unit, and that is an accepted exception
to the one-store rule** (c-747, review r1.F6, decided 2026-10-11). The rule is that
`state/board.db` is the only state and nothing else has to agree with it. The note does
not hold anything the board knows or could know: it is not about a card, a gate or a
session, it is about this machine's service manager, one fact ("the drain's bring-up
loaded this service and has not seen it run", and how many drain starts have tried). The
record it sits beside is already a file for the same reason: the rendered unit in
`<dir>/services/` is how `missing` knows the install had a service, and neither is copied
into the board. A row in the board would make the board answer for launchd and systemd,
and would travel with a board that is imported or restored onto another machine, where it
would be false. It is kept small on purpose: one writer (the bring-up), read only at a
drain start, removed by a process being seen, by the owner's own verb, by a stop the
manager reports, and after three tries, so a note that is wrong costs at most one start
made or not made, which `shipyard service start` or `stop` corrects. (The decisions
record left this tree with c-722 and is now `<install>/history/docs/decisions.md`, outside
the checkout, so the decision is recorded here, on the page that owns the note.)

**A stop made with the manager's own command counts too** (r1.F4,
`service.Manager.resting`). `systemctl --user stop dev.shipyard.fetch` goes through no
`shipyard service` verb, so it removes no note, and it leaves the unit enabled with no
pid: exactly what an owed start looks like. So before it starts anything,
`start_loaded` asks the manager whether the unit is at rest, and on systemd that is
`ActiveState=inactive`: the note is dropped and nothing is started. A unit that crashes at
start is not inactive, because the units are rendered with `Restart=always` and no start
limit, which holds a crashing unit `activating` between runs; only a stop rests it. That
is reasoned from systemd's documented states and was NOT measured in this card (no Linux
machine at hand): if a real unit is ever seen inactive without a stop, the cost is one
owed start not made, and `shipyard service start fetch` makes it. On launchd there is
nothing to read: a stop is a bootout, the label is no longer loaded, and that already
drops the note. A fetch role
running by hand holds the retry as it holds the bring-up (`fetch_held`).

**`status` says when fetching is not happening**: under the fetch service's line, while it
is not running and segments with a fetcher are installed, `nothing fetches 2 installed
segments (daybook, oci): `shipyard service install fetch`` (`appservices.status_line`;
always `install`, which starts whatever is not running, whether its unit is missing or loaded with no pid, r2.F1).

`install` and `start` of the drain refuse while another Shipyard drain
runs as this user on this machine (`keel/drainprobe.py`, [import](87-import.md)), naming its
pid or label and the command that stops it. The labels are fixed, so one install per user has services; a
second runs by hand, and `service install` refuses a unit of the label that names another
install's config rather than take its services over. `shipyard service` refuses a config that is not an install's.

**One interface, three answers** (`keel/service.py`): `platform()` is launchd on macOS
(LaunchAgents in `~/Library/LaunchAgents`), systemd on Linux (`systemd --user` units in
`~/.config/systemd/user`), and `unsupported` anywhere else, where every manager verb raises
`service.Unsupported` with one plain message. On Linux the units stop at logout unless the
user lingers (`sudo loginctl enable-linger <user>`, the one step that needs root). A shell
with no user bus (`su`, `sudo -u`, cron) is handled: `service.systemctl` fills in
`XDG_RUNTIME_DIR` and the bus address from `/run/user/<uid>` when lingering runs the
manager, and "Failed to connect to bus" is said with that fix (c-621, the clean-user run); the doctor
says so.

## The doctor on an install

`keel doctor` on an install's config (or with `--single`) leaves out the checks an install
does not have (`doctor.single_machine`) and reports: config, state, spaces, `claude` and its login, the board,
the deck, lingering, on WSL whether systemd runs (c-804), the browser pool, ghost houses, and the drains running as this user
(this install's, and any other, which is a problem), and git's identity, whose absence is
a problem since no outcome can land without it (c-621; only here, so the live config's doctor
prints what it did). Where git itself is missing it says that instead, in the git check's
own sentence and fix, and nothing of the identity: `prereqs.git_checks` is the one guard
(git, then its name and email only where git is), shared by `prereqs.gather` and the doctor,
so a missing git is never read as settings that "could not be checked". Its `memory` lines
(every config, `memoryroot.report`) say where Bosun's memory, the talker's and the profile
are read from, which parts are still the checkout's, and each shipped template that moved on
since the install was seeded; none of them is a problem. Its `fetch` line (c-742) says
whether a process runs the fetch role for this install (`drainprobe.fetching`: `fetch` as a
loop, or `run` naming the role, with this install's `KEEL_CONFIG`), and none running while
segments with a fetcher are installed is a problem that names them and the command:
`fetch: nothing runs the fetch role, so 2 installed segments (daybook, oci) never refresh`.
Each segment's fetch age follows, as on every config ([segments](70-segments-and-fetch.md)),
now that an install fetches. It leaves out the voice gateway
unless it is installed, the talker and Docker Desktop's room. On an install its "cloned but not listed" check looks only
in the folders of the repos the user listed, never beside the code checkout (c-618; the
live config's scan is as before): the folder
Keel was cloned into holds whatever else the user keeps there, and none of it was chosen.

## What has been proven, and what has not

Proven on a Linux machine as an ordinary user with HOME pointed at a fresh empty directory
(2026-10-01): init from nothing, every check green, the layout, config, board, trust and
wrappers made, nothing written under that HOME's `~/.claude`, the login correctly reported
as not logged in with the command printed, the services rendered by `--dry-run-services`
(that machine had no user bus for that user, so no real unit was installed), the doctor in
install mode, a second run keeping the config byte for byte, and the deck started
from the install's wrapper by hand, answering `/` and `/api/state` with an empty board.

Not yet proven, and owed by a clean user on a real machine: a real `claude /login` and the
probe turning good; real launchd and systemd units starting, surviving a logout (linger) and
a reboot; a clean macOS user end to end (Homebrew Python, `/tmp` symlinks, the keychain
login); and a first card run by the installed drain. Native Windows imports Unix-only
modules in the core, so it is refused by the checks rather than by the service interface
alone. WSL2 has not yet been proven end to end on a real Windows machine either.

## Files

- `bin/shipyard`: the command; the same CLI as `bin/keel`.
- `keel/installer.py`: `shipyard init`.
- `keel/memoryroot.py`: the install's memory and profile, seeded, read install first, and
  the doctor's `memory` lines ([Bosun](96-bosun.md), "Where the memory lives").
- `README.md`: what Shipyard is, the install command and what it needs, the first run.
- `keel/prereqs.py`: the machine checks, each with the three parts of its miss, and the
  write of git's name and email.
- `tests/test_prereqs.py`: every failing check carries the three parts, init's line says
  them (literal lines), each platform's exact commands, the npm command only where npm is,
  a help that did not answer, no name or email printed to paste, and the save: what git
  then reads, a set name surviving, a refusal once both are set, a dash-leading value, a
  second write git refuses (git's global file a temp file throughout).
- `keel/builder.py`: the builder an install ships with ([Bosun](96-bosun.md)).
- `keel/appservices.py`: the install's deck, drain and fetch role, `shipyard service`, and
  `bring_up`, which the drain calls as it starts; "started" said only of a service with a
  process (`settled`), and the note a bring-up with none leaves (`pending`).
- `keel/service.py`: the one service interface (launchd, systemd, a refusal): a load that
  ends with a kickstart on macOS, and `running`, the bounded wait for a pid.
- `tests/test_service.py`: the commands a load, a start, a stop and a restart run on each
  manager, every `launchctl` and `systemctl` patched: the kickstart after the bootstrap
  (none after a failed one, none for a scheduled job, never `-k`), a start that bootstraps
  only what is not loaded, and the wait for a pid, bounded, with its pause handed in; a
  kickstart that complains with a process there (a good load, an ok start) and with none
  (the failure), a scheduled job never kickstarted by a start, loaded or not, and
  `resting` reading `ActiveState` on systemd only.
- `tests/test_appservices.py`: c-742's reproduction, kept (an install's rendered services
  run its segment's fetcher and the state document lists it, before its first pass as not
  fetched); the fetch unit for macOS and Linux; `install` bringing up all three and
  restarting none the second time; a missing service added alone; the drain's start
  bringing up the one that is missing, never on a by-hand install or another install's
  units; `status` and the doctor naming a fetch role that is not running. And c-747's
  reproduction, kept (`StartedTest`: the manager's stand-in answers as launchd did, loaded
  with no pid and runs 0, and the drain's log must not say "started"): the failed step
  that stays installed, the next start starting it and not reinstalling, one that came up
  by itself left alone, a stop or an uninstall ending the retry, and `install` and `start`
  saying "started" only with a pid and exiting 1 without one. From review round 1: the
  note gone after each of `stop`, `uninstall`, `start` and `install` and still there after
  a refused one, a unit stopped with the manager's own command not started again, and the
  owed start made at three drain starts and then given up, said once.
- `etc/shipyard.example.toml`: what `config.toml` is made from.
- `tests/test_installer.py`: an install is made under the directory chosen with only its
  packs repo listed, its builder clone and key made, and a second run keeps the config, the
  key and the board; a required miss stops init with its three parts said and nothing made;
  and an install with no git name and email completes, says the page asks for it, and
  commits its packs repo as Shipyard (with only the email set, too).
