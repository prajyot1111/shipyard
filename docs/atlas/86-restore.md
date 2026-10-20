# Restore

Getting Keel back on a machine that has lost it, from the backup store alone. This is the
runbook for the day the disk is gone. It is done by hand: nothing automates it, and no
rehearsal of it runs (see the end).

The store holds everything the machine needs except what only the user holds. The code comes out
of the store too: the repo has no remote, so the `code` set carries it as a git bundle
([the backup](85-backup.md)). The same recipe is written in the store's own `README.md`, so
it is there with nothing else in hand.

## What only the user holds

| What | Where it goes | If it is lost |
|---|---|---|
| the passphrase, "Keel backup passphrase" in the password manager | `~/.keel-backup/backup.key`, mode 600 | every snapshot is noise; there is no recovery, which is why it lives off every machine |
| the helm passphrase, "Keel backup passphrase (helm set)", only if the helm set is wanted | asked for by `gpg`, or `~/.keel-backup/` as the tool names it | that set is noise |
| the store's login, "Keel backup store login" in the password manager: the contents of `rclone.conf` | `~/.keel-backup/rclone.conf`, mode 600 | make a new one: `rclone config` on any machine with a browser, a Google Drive remote named `keel-drive`, scope `drive.file`, with the desktop OAuth client from the Google Cloud project `bin/keel-backup-setup` made (its Credentials page shows the client id and secret) |
| the Google TTS key | `keel voice key set` | a new key in the same personal Google project, restricted to the Text-to-Speech API |

Keep `rclone.conf` in the password manager beside the passphrase (decided on c-288). A store
you cannot log in to is as lost as one you cannot decrypt.

## The runbook

1. **Put the two secrets in place.**

   ```
   install -d -m 700 ~/.keel-backup
   (umask 077; cat > ~/.keel-backup/backup.key)      # paste the passphrase, then Ctrl-D
   (umask 077; cat > ~/.keel-backup/rclone.conf)     # paste the store login, then Ctrl-D
   ```

2. **Get the code.** The newest `code` snapshot is one encrypted file in the store,
   `sets/code/snapshots/YYYY/MM/<id>.tar.gz.gpg` (the newest id is named by
   `sets/code/latest.json`). Fetch it with `rclone copyto` using the login above (or
   download it from Drive), then decrypt and unpack it with `gpg` and `tar`, as the store's
   `README.md` says. It holds `code/keel.bundle`. Clone from it:

   ```
   git clone code/keel.bundle ~/keel
   ```

   The clone is on `main`. Every other branch and tag the old checkout had is in the
   bundle too (`git bundle list-heads` names them).

3. **Restore the data into a scratch directory.** From the new checkout:

   ```
   ~/keel/bin/keel-backup restore --set keel --into ~/scratch/restore
   ~/keel/bin/keel-backup restore --set harbor --into ~/scratch/harbor    # if wanted
   ~/keel/bin/keel-backup restore --set helm --into ~/scratch/helm        # if wanted
   ```

   `restore` reads the store by default (`--local` reads the mirror, `--snapshot <id>` picks
   an older one). It refuses a destination inside the live checkout or the install's home,
   because untracked files there would dirty a tree that is in use. So it never goes
   straight into place: unpack
   into a scratch directory, look at it (`state/board.db` opens with `sqlite3`), then move
   what you want where it belongs. A restore is not a merge, and nothing in an archive knows
   what is already on the disk. A card's `scratch/` folder (`state/cards/<id>/scratch`) is
   not in a snapshot (c-752), so a restored card directory comes back without one; the
   whole list of what the set leaves out is in [backup](85-backup.md).

4. **Move it into place.** The `keel` set unpacks relative to the install's home (the
   parent of its state dir, c-622): `state/` (the board, the card directories, the boards,
   the voice data), `segments/*/data`, and the install's `config.toml` when it had one. Put them under the install's directory, with
   the services stopped while you do it.

5. **If the machine is new, make an install.** Run `shipyard init <dir>` from the
   checkout ([install](88-install.md)): it checks the machine, lays out `<dir>`, writes
   `config.toml`, makes an empty board and the builder's key, and installs the deck and
   drain services. Do this before step 4, then put the restored `state/`, segments,
   `config.toml`, `memory/`, `identity/`, `packs/`, `history/`, `spaces/` and
   `claude/projects/*/memory` over the empty ones with the services stopped, so the board
   you restored is the board the install runs. The files of `memory/` and `packs/` come
   without their `.git`; their history is `repos/memory.bundle` and `repos/packs.bundle`.
   Give each its history back in this order, for memory and then for packs (r2.F7):

   ```
   git clone --no-checkout <restore>/repos/memory.bundle /tmp/memory-history
   mv /tmp/memory-history/.git <dir>/memory/.git
   git -C <dir>/memory reset -q
   git -C <dir>/memory status
   ```

   and the same four lines for packs (`repos/packs.bundle`, `/tmp/packs-history`,
   `<dir>/packs`). The clone goes to a temporary directory, since `memory/` already holds the
   restored files; its `.git` moves in under them. A `--no-checkout` clone writes no index, so
   `reset -q` (a mixed reset to HEAD, which touches no file) builds it from HEAD (r3.F10);
   without it `status` would list every committed file as a staged deletion. `status` then
   lists what was not committed when
   the snapshot was taken (the talker's own memory writes), kept as files for you to commit
   or leave. To fold a restored `keel` snapshot into a fresh install
   instead, `shipyard import` reads it ([import](87-import.md)); it refuses an install that
   already has cards.

6. **Finish what is the user's.** Set the Google TTS key (`keel voice key set`, then `keel voice
   audio` renders the clips again), log the install's `claude` in, and run `keel doctor`
   and open the deck.

## What comes back, and what does not

| Comes back | From |
|---|---|
| the board, every card directory, every blackboard, the voice data (transcripts, the TTS meter) | the `keel` set |
| every segment's data, and the install's `config.toml` | the `keel` set |
| the code, every branch | the `code` set |
| the old engine's segment data and ledgers | the `harbor` set |
| the retired PR tools' history | the `helm` set |

Left out on purpose, each regenerated or not state ([the backup](85-backup.md) has the
reason for each): `state/logs/`, `state/worktrees/` (their branches are in the bundle),
`state/drafts/`, `state/fetch-locks/`, `state/talker.pid`, `state/human.token` and
`state/artifact.key` (made again on first use), the TTS clip cache, `node_modules/`, video
and audio files, and each card's `merged-tests.log` (a refusal's text may still name it;
the deck shows no link, and approving again reruns the suite and writes a new one).

**Not backed up by any set today:** the review pages under `.lavish/`, and the spaces'
Claude config dirs (`spaces/*/.claude`, `~/harbor/spaces/personal/.claude`): session
transcripts, history and their memory files. A restored machine starts those empty.

**Snapshot history from before 2026-09-19** stays in the old GitHub repo for 90 days, to
2026-12-18, and is then let go: no migration. Every snapshot still retained on the move day
was already copied into the store by `keel backup migrate` and read back.

## What is not proven

Nothing rehearses this runbook on one machine. A script that restored a host from the seed,
and a quarterly card that ran it in a container, were part of the two-machine setup and are
gone with it. The pieces are each proven: the weekly `keel backup verify` restores every set
the machine writes and checks its canary, and `bin/keel-backup-selftest` covers the tool. A
rehearsal of the whole by-hand path on one machine would be a new card, and a restore is
owed one before anyone relies on this page for a real loss.

## Where it lives

- `bin/keel-backup`: `restore`, `verify` and the store's `README.md` text
  (`write_store_readme`).
- `bin/keel-backup-setup`: the store's login, made once.
- `bin/shipyard`: `init` and `import` for a new machine.

## How to change it

A change to what a new machine needs (a new secret, a new step) changes the table at the top
and the runbook here in the same commit, and the store's `README.md` text in
`bin/keel-backup`, which says the same thing without Keel.
