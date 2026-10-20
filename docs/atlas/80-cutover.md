# Cutover

Keel runs on one machine. An earlier version ran across two, with a remote board, a door
between the decks and a scripted move from one to the other; none of that code is in the
tree (c-622). There is no cutover to run, no second host to prepare, and nothing on this
page to follow step by step. The page is where what is left of that version is found.

## What is left of it

- **The import path.** `shipyard import` still reads a snapshot made on a two-machine
  install and clears the settings that no longer apply (`keel/importconfig.py` lists them:
  hosts, tenancy, console, backup, the restore rehearsal card, the board URL). The one-time
  fold of the old Harbor ledger into the board is `keel/importer.py`. Both are on
  [import](87-import.md).
- **Ignored config keys.** An old config file still loads. `[hosts.<name>]`, `[tenancy]`,
  `[keel] board_url` (also under `[machine]`) and a space's `host` key are read, ignored,
  and named once in `Config.warnings`. `KEEL_HOST` and `KEEL_URL` are not read. This
  machine's limits are `[keel]` keys: `houses_max`, `reviews_max`, `browsers_max`,
  `memory_floor_mb`, `house_mb`, `house_nice` and `idle_resume_minutes`. See
  [start here](00-start-here.md), "The configuration".
- **Backup sets.** What this machine backs up is `[backup] sets` and `[backup] pull`. While
  `[backup]` does not say, an old `[hosts.<this host>]` `backup_sets` or `backup_pull` is
  still read, so an old file keeps backing up. See [the backup](85-backup.md).
- **Restore by hand.** A new machine is restored from a backup snapshot with no script
  that brings the whole host up. The steps, and what the store's README says, are on
  [restore](86-restore.md). A one-machine restore rehearsal does not exist; it would be a
  new card.

## The old tree

- `~/harbor` is read-only history. Nothing in Keel writes into it, and `~/harbor/segments`
  stays in place as the tree the segment data was copied out of.
- `[machine] harbor_dir` names that tree. Two things still read it: the talker, which seeds
  its login state from `.claude/.claude.json` under it, and the ledger import, which reads
  `ledger/cards.jsonl` under it when `--ledger` is not given. Unset, neither applies.
- The old agents are parked, not deleted: their plists sit in
  `~/Library/LaunchAgents/unloaded/`, so that a reboot does not bring them back. Keel does
  not unload, edit or restart them.

## Where it lives

- `keel/service.py`: one service as a launchd plist or a systemd user unit, and loading,
  reading, restarting and removing it. Every `install` verb renders its file with this
  machine's paths into `Config.services_dir`: an install's own `services/` (c-722), never the
  code's `etc/`, which only a checkout with no install still uses.
- `keel/install.py` and `dev.keel.plist`: the engine's service (with `KEEL_CONFIG` when its
  config is not the checkout's own, c-711).
- `keel/talker.py` and `dev.keel.talker.plist`: the talker's. The login step is in
  `<install>/history/docs/talker.md`.
- `keel/voice.py` and `dev.keel.voice.plist`: the voice gateway's.
- `keel/backup.py`, `dev.keel.backup.plist`, `dev.keel.backup-verify.plist` and
  `dev.keel.backup-pull.plist`: the backup's jobs, on [the backup](85-backup.md) (a new
  install's are `dev.shipyard.backup*` since c-729; a machine with the old ones keeps them).
- `keel/dockerroom.py`: the doctor's `docker` line. On macOS with spaces served, it reads
  Docker Desktop's memory against the machine's. Six GB or less left for macOS is a problem
  (measured 2026-09-26: Docker holding 10 GB of 16, macOS swapping 6 of 7 GB). It only reads;
  elsewhere the line says "not applicable".
- `keel/backupdue.py`: the doctor's `backup` line, the last good run, and a problem when
  the drain has counted the hourly snapshot overdue ([the backup](85-backup.md), "When the
  hourly job stops").
- `keel/doctor.py`: `keel doctor`, the resolved setup with live board counts. Its `board`
  line counts live cards only: archived cards and tracking cards (those with children) are
  counted apart.
- `keel/importconfig.py` and `keel/importer.py`: the import path above.

## Where the history is

Why Keel has this shape is in `<install>/history/docs/plan.md` and `<install>/history/docs/decisions.md`. The two-machine code,
its scripts and its selftests are not in the tree and are not described here.

## How to change it

Keep this page short. If a new one-time move ever needs steps, they belong on a card and
in the commit that does the move, and they are deleted from the Atlas once it is done.
