# Import

`shipyard import <dir>` brings an existing Keel (the board, the card directories, the boards, the
voice data, the segments and the choices in its old config) into an install made by
`shipyard init` ([install](88-install.md)), so a two-machine Keel becomes one install (card c-620).
It reads a snapshot and never writes it; it writes only the install.

## The runbook

On the machine that holds the old board (the old Keel's board host), take a snapshot of the
`keel` set with nothing moving:

```
# drain_paused = true in the old keel.toml, then wait until no personal house is busy
keel backup run --force --set keel
```

On the machine the install is on, bring it down and unpack it outside every checkout, then
import into the install, dry run first:

```
bin/keel-backup pull
bin/keel-backup restore --local --into ~/scratch/move
<install>/bin/shipyard import ~/scratch/move --old-config ~/keel/keel.toml --dry-run
<install>/bin/shipyard import ~/scratch/move --old-config ~/keel/keel.toml
<install>/bin/shipyard import --verify          # the checks again, any time
```

The snapshot does not carry the tracked `keel.toml`, so `--old-config` names the old config
(by default the checkout's own `keel.toml`). `--root OLD=NEW` maps an old state root by hand,
`--work-config-dir` picks the work space's Claude dir (below), `--replace` imports again.
`--map-space OLD=NEW` carries a retired space's cards into one the install has (for example
cards in `console`, Bosun's space before its cards moved to personal: `--map-space
console=personal`); without it a card in a space the install will not have refuses the import,
and the refusal names the flag. The verify counts the source's cards under the mapped name.
When the old config ran Bosun as the superuser (`[builder] superuser = true`), every personal
repo Bosun built is added to the install's `[builder] repos` (`importconfig.builder`), so the
drain starts no house on Bosun's assigned cards; superuser itself is not carried, since it needed
Bosun's own Unix user here (without this, an import starts houses on Bosun's cards).

**Two drains must not share `~/.claude`'s houses.** Before the install's drain starts, the user
unloads the old `dev.keel` drain on this machine (the human's step, as every launchd change is). It is
held by mechanism, not by this sentence: `keel/drainprobe.py` finds every Keel drain running
as this user on this machine (a `bin/keel` or `bin/shipyard` process running `drain`, or
`run` with `drain` among its roles, its `KEEL_CONFIG` read from its environment; a loaded
launchd agent or active systemd user unit labelled `dev.keel`, `dev.harbor.worker`, or a
`dev.keel*`/`dev.harbor.*` label naming a drain), and `shipyard import` and `shipyard service
install|start` (the drain, or both) refuse while one that is not this install's runs, naming
its pid or label and the command that stops it, which they never run themselves. The import
also refuses while this install's own drain runs (a process with its `KEEL_CONFIG`, or
`dev.shipyard.drain` active) or its deck answers. The doctor of an install says the same. The way back: `shipyard service stop`, unpause the
old Keel's drain, load the old agents again. The import never writes the snapshot or the old
Keel's machine, and its services stay installed.

## What comes, and what does not

| Comes | How |
|---|---|
| `state/board.db` | copied with sqlite's backup API into `state/import/`, migrated (opened as a Board), every edit below made in one transaction, `integrity_check`, then renamed into place |
| `state/cards/`, `state/voice/`, `state/review-settings.json` | copied byte for byte |
| `state/boards/` (its trash too) | copied, each JSON file's paths moved like the board's |
| each segment any `[hosts.*] fetch` names | its tracked code from the checkout and its `data/` from the snapshot, into `<install>/segments/<name>/` |
| the choices in the old config | `keel/importconfig.py`, below |
| memory (`bosun/memory`, `<checkout>/talker/memory`, `<checkout>/identity/`) | not copied: an install reads its own `memory/` and `identity/` (c-722, [Bosun](96-bosun.md), "Where the memory lives"), and the checkout's only for a part it does not hold yet. For such a part the import refuses while a checkout has uncommitted changes under its path, naming them (`stateimport.memory_paths`); `shipyard move-personal` ([install](88-install.md)) is what brings the memory in |

Everything else under the snapshot's `state/` is named as skipped (`console/`,
`console.json`, `login.json`, `logs/`, `worktrees/`, a lock, `.attached`). The old machines'
Claude config dirs (`[hosts.*] config_dirs`, `[console] config_dir`) are not imported;
the report lists them with the auto-memory files it can read, so the user can carry by hand what
they want. Bosun and the talker start fresh.

## The board's edits (`keel/importboard.py`)

**Paths.** The old roots are found from the stored values (`keel/importpaths.py`): every
prefix ending in `/<checkout>/state/`, the first one in a path, where `<checkout>` is the
name of the git checkout the old config sits in (`keel` when it is not in one), so the box's
`/home/ubuntu/keel/state/` and the laptop's `/Users/<name>/keel/state/` are both found, and
printed, while a work path that merely has a `state/` in it is not. Each maps to
`<install>/state/`; `--root OLD=NEW` maps one by hand, and adds a root of another shape. Rewritten: `plan_ref`,
`output_ref`, the same two keys in an event's data, every string in `options` (`add_dirs`,
`tier_reads`, an audit's copies), every string in a board file. A value moves only when it
starts with an old root. Free text (a brief, a block reason, an event's words, an ask) is
never rewritten, and the dry run counts its mentions; a card's files are copied as they are. A work worktree (`options.worktree` under the user's
workspace) is not under a state root, so it stays as it is.

**Two-machine fields.** Cleared: `options.host` (the pin), `options.claim`,
`options.publishing` (the door's marker), `options.landing`, `options.rotate` and
`options.dropin_hold` (a step in flight on the old machine), an open ask's `claimed_by` and
`claimed_at`, and a waiting request's `taken_by` (a taken one is open again: Bosun starts
fresh). A pending relay addressed to another host than this install's is marked carried
(`superseded`, "dropped by import"), the one row the import adds, so this drain never acts
on a tap meant for a machine that is gone; the report lists each. Holds are kept. No other
event is added or edited beyond the ref rewrite. An option path on a box home (`/home/...`)
that is not on this machine is left as it is and listed in the report.

**Sessions.** A work card keeps its `session_id`, which is valid while the work space keeps
its Claude dir. An open personal card's session ran on the box: its id is cleared and the
card blocked, "imported: the session stayed on the box; Resume starts fresh from the card
dir". A done card keeps its id.

**Worktrees.** An open personal card past `assigned` had a worktree on the box. If its
branch (`keel/<id>-*`) is in the repo here, the worktree is cut again with `git worktree
add` at `<install>/state/worktrees/<id>`; if not, the card is blocked, "imported: branch
keel/<id>-* is on the box", and the dry run prints the `git fetch` that brings it over.
A recut git refuses (the branch is checked out elsewhere) blocks the card with git's words.

## The config (`keel/importconfig.py`)

Written once through `setupconfig.edit` (the hash check, the backup under
`state/config-backups/`, the reload), each key set in place with its comment kept and left
alone when it already says the same.

- **personal**: each listed repo whose checkout is on this machine, as an existing
  checkout (never cloned; a missing one is named), and `projects_dir`, `model`, `confirm`,
  `house_review`, `pipeline`.
- **work**: the pack turned on as Setup turns it on (`packsetup.pack_space`), `config_dir`
  from `--work-config-dir`, then the old space's repos that are here and its own keys (not
  `host`, `adapter`).
- **carried**: `[tests]`, `[house_tests]`, `[integration]`, `[retests]`, `[deploy_tests]`, and each `[keel]`
  switch the shipped example has, except `drain_paused`, which the install keeps.
- **never**: `[hosts.*]`, `[tenancy]`, `[console]`, `[backup]`, `board_url`, the door's
  `url`, `[recurring.restore-rehearsal]`.

A card in a space the install will not have refuses the whole import, by name.

### The work space's Claude dir (a-88)

| `--work-config-dir` | What it means |
|---|---|
| unset: the old config's value, `~/.claude` (recommended) | work houses keep the existing login, skills and session history; a work card's session id still resumes |
| `<install>/claude` | the install's own dir, as a fresh install has; the user logs the work space in there, and an open work card's session id is cleared and the card blocked like a box session |

## Once, and again

`--dry-run` writes nothing and prints every change as `table/id field: old -> new`, every
file copied or skipped, the segments and the config diff. A real run writes
`state/import/record.json`, `"status": "in-progress"` before its first write and `"done"`
after its last (the source, the time, the roots, what it blocked and dropped). A run that
stopped part way is resumed by running it again from the same snapshot. A second run of a
done import refuses, "already imported from X at T", and so does an install whose board
already has cards. `--replace` moves `state/` aside to `state/pre-import-<time>/` and
imports again, refused once the install's drain has started a house since (a `session` or
`resume` event after the import's last one, or with no record the snapshot's highest event). An install whose deck answers is refused: stop its services
first. A snapshot with a non-empty `board.db-wal` beside the board is a live board and is
refused. The same snapshot gives the same result.

## Verify (`keel/importverify.py`)

After every import, and on `--verify`: rows per table and cards per space and stage equal
to the snapshot's (its events plus the relays it dropped); every file under `state/cards/` the same bytes; no stored value still
under an old root, and every rewritten path the snapshot had present here;
`integrity_check`; `kb lint` over every plan on both boards, reporting only the findings
the import introduced; and the single-machine doctor's lines, said but not counted (a deck
or a login not started yet is not the import's fault). The result is
`state/import/report.md`; exit 1 when a counted check fails.

## Proven

On the Linux box (2026-10-01), with the live board unreadable to the builder's user, the
demo sandbox's board copied through the backup API plus two-machine rows added to that
copy, imported into a fresh `shipyard init` install: the dry run, the real run, the second
run refused, `--replace`, and `--verify` passing. Owed: the real move, from the old
Keel's own snapshot.

## Files

- `keel/stateimport.py`: the verb, the source checks, the allowlist, the segments, the
  record and `--replace`.
- `keel/importboard.py`: the board's edits, planned from the snapshot and made in one
  transaction.
- `keel/importpaths.py`: finding the old roots and moving a value under one.
- `keel/importconfig.py`: the choices carried into `config.toml`.
- `keel/importverify.py`: the checks and the report.
- `keel/drainprobe.py`: the drains running as this user here, for the import, `shipyard
  service` and the doctor.
- `tests/test_stateimport.py`: a dry run writes nothing, the import's edits and blocks, a
  second run and `--replace`, a stopped run resumed, another drain and the install's own
refusing, a leftover root fails verify, the config, uncommitted memory.
