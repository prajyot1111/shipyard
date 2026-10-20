# The backup

`state/` is the only irreplaceable thing on this machine. The board is the single store,
a card directory holds the plan and the output a session wrote once and will never write
again, and the segment data is every daybook thread, every fathom note and every bill
already read. None of it is in git, deliberately: a tracked file a fetcher rewrites leaves
the checkout dirty on a schedule.

So there is an encrypted copy, hourly, in a store off the machine (Google Drive, through
rclone), a weekly proof that the copy can be read back, and a nightly pull of the recent
end of the store onto the machine's own disk, so there are two copies off the machine
running Keel. The
code rides along as its own set, because the repo has no remote: without it a restore
brings back a board with nothing to run it ([restore](86-restore.md)).

## The shape

| Piece | What it is |
|---|---|
| `bin/keel-backup` | the tool: scope, encryption, retention, the store, restore, verify, pull, status |
| `bin/keel-backup-selftest` | its proof, against a fabricated tree and a directory standing in for the store |
| `bin/keel-backup-setup` | the wizard that sets up the Drive store, once (8 stages) |
| `keel/backup.py` | `keel backup`: the jobs, `keel backup env`, and the verbs that drive the tool |
| `keel/backupdue.py` | the drain's watch on the hourly snapshot: the run it starts, the notice it files, the doctor's line |
| `keel/backupsetup.py`, `keel/backupstatus.py` | the first run's turn-on, and what its step shows of the backup as it is observed ("Turned on from the first run") |
| `keel/backupslim.py` | the sums behind `keel backup slim`: what an old snapshot loses, by rule, and the proof it lost nothing else ("Slimming the old snapshots") |
| `keel/backupslimapproval.py`, `keel/backupslimjournal.py`, `keel/backupslimreport.py` | that rewrite's approval file (what the dry run showed), its journal in the store, and what a run prints |
| `dev.shipyard.backup.plist`, rendered by `keel backup install` into the install's `services/` (`Config.services_dir`, c-722; a checkout with no install, its `etc/`) | the hourly snapshot job (on Linux a `.service` and `.timer` pair) |
| `dev.shipyard.backup-verify.plist` | the weekly restore proof, Sundays at 04:30 |
| `dev.shipyard.backup-pull.plist` | the nightly pull's backstop, 03:00, only where `[backup] pull` is on; the drain runs it when due |
| `~/.keel-backup/` | the passphrases, the store's login (`rclone.conf`), `state.json`, `work/`, `mirror/`, the logs, the locks (`.lock`, `.pull-lock`, and a slim's `.slim-lock` with `.slim-lock.work`, the record of where its unpacked work is), a slim's `slim-approved.json`, `work/<set>/slim-old.tsv`, the kept old archives as last listed, which status reads, and `work/<set>/slim.json.prev`, this machine's copy of a slim's journal as it last stood |

**The labels are the install's** (c-729): `dev.shipyard.backup`, `-verify` and `-pull`, as
the deck and the drain are `dev.shipyard.*` (`appservices.PREFIX`); a stranger's install
showed `dev.keel.backup` beside them. A machine whose jobs were installed under the old
labels, `dev.keel.backup*` (a file of that family where the service manager loads from, or
where the jobs are rendered: `backup.kept_old`), keeps them: `backup.label_of` names every
job by them there, so a backup that runs is never renamed out from under it, and the first
run's one-backup-per-user check still finds it.

```
keel backup install [--load]   write the jobs; --load starts them (launchd or systemd)
keel backup uninstall          stop them all and remove the manager's copies
keel backup status             the jobs, then freshness, size and what is retained
keel backup run [args]         one snapshot now (the hourly job runs the same thing)
keel backup verify [args]      one restore proof now (the weekly job runs the same thing)
keel backup pull               one copy of the store into the mirror now (the nightly job)
keel backup init               prove the store is reachable and make the keys, once
keel backup migrate            the one-off move off the old GitHub repo
keel backup slim [args]        rewrite the retained snapshots without what the backup now leaves out
keel backup env                the config's backup settings as shell exports
```

Everything after `run`, `verify`, `pull`, `init`, `migrate` and `slim` reaches the tool unparsed,
so `keel backup run --force --set keel` arrives whole. The tool's own exit code and its own
words come back; nothing in `keel/` rewords them.

**The tool is bash and stays bash.** Every promise it makes is about how `tar`, `gzip`,
`gpg` and `rclone` behave, and it carries over 2,000 lines of reasoning about cases that
were got wrong once. `keel/` being stdlib Python is a rule about Keel's modules, not a
reason to translate a hardened script into an unhardened one. It runs on macOS and on
Ubuntu: GNU and BSD differ in `stat`, `sha256sum` and whether `tar` guesses compression, and
the selftest passes on both (a Linux run found the last of those).

## The store

A store is where the snapshots go, named once in the install's `config.toml`:

```
[backup]
store = "rclone:keel-drive:keel-backup"
rclone_config = "~/.keel-backup/rclone.conf"
```

A backup turned on from the first run also carries `since`, the time it was turned on
("Turned on from the first run", below); a store set up by hand has none.

`rclone:<remote>:<path>` is an rclone remote (Google Drive today, so another provider is a
config change, not a code change); `file:<dir>` is a directory, which is what the selftest
uses and what the mirror is. Inside it every set lives at `sets/<set>/`: one object per
snapshot at `snapshots/YYYY/MM/<id>.tar.gz.gpg`, and a `latest.json` naming the newest
snapshot, the host that wrote it and the digest of its plaintext manifest. A `README.md` at
the root says how to get everything back with `gpg` and `tar` alone, and it
carries the by-hand recipe for a machine with no Keel on it: clone the newest `code`
snapshot's bundle, put the passphrase and `rclone.conf` in place, then
`bin/keel-backup restore --set keel --into DIR` ([restore](86-restore.md)). The store no
longer gets a restore script; an old `restore-seed.sh` may still sit there, unused. A set
that has been slimmed also holds `slim.json`, the journal of that rewrite, with
`slim.json.prev`, the journal as it stood before its last change, and for the
seconds of one replace an object under `slim-tmp/<set>/`. Beside `sets/`, and until
`slim --purge`, the store holds `slim-old/<set>/`: the whole archive each rewrite replaced,
so a slimmed set takes its old space and its new space both ("Slimming the old
snapshots"). Status shows that figure apart from the sets (`slim_old_mb`, and per set),
and the size warning adds it to theirs.

**Publishing is proven, never assumed.** A snapshot is encrypted into
`~/.keel-backup/work/<set>/pending/`, decrypted and compared against the archive it came
from, put into the store, and then checked against the md5 the store itself lists for it.
Only then is `latest.json` written: it is the commit point, and a `latest.json` naming a
blob the store does not hold is the one lie this must never tell. A run that dies anywhere
in between leaves the blob in `pending/`, and the next run publishes it before anything
else, so a snapshot that never reached the store cannot pass for a quiet night.

**The md5 itself is held to three rules** (`md5_of`, `same_md5`; c-724). The system's own
tool (`md5sum`, `md5`, `/sbin/md5`) is used where there is one, since a run asks for
dozens of digests, but only a tool that proves itself when the run starts: it must give
the md5 of no bytes for `/dev/null`, exactly, or Python does the hashing. Whatever ran,
a digest is 32 lower-case hex characters or it is nothing: `md5_of` prints nothing and
fails otherwise, as it does for a file it cannot read. And two digests are the same only
when both are digests: every comparison that proves a write goes through `same_md5`, so
an empty string never equals an empty string. `tests/test_backupmd5.py` runs the tool
with stand-ins for the system tool that print nothing, print something else, fail, or
break after proving themselves.

**The Drive login is an OAuth refresh token**, not a key: `bin/keel-backup-setup` walks the
Google Cloud project, the consent screen, a desktop OAuth client and one browser login, and
leaves the token in `rclone.conf` (0600, outside every set and every repo). Two things there
are load-bearing:

- The app is **published to production**. An app left in "testing" gets refresh tokens that
  die after 7 days, and the hourly job would stop a week after setup.
- The scope is **`drive.file`**: the token sees only the files this app created, never the
  rest of the Drive, and the scope is non-sensitive, so publishing needs no Google review.

A token that dies anyway (a revoked grant, a changed password) raises `backup-auth` on the
first refused run, with the fix: rerun the wizard, which skips everything that still works.

**Why not GitHub any more.** It was a private repo with exactly one orphan commit, rewritten
and force-pushed hourly, because encrypted blobs do not delta-compress and history would
have kept every snapshot forever. That was a lot of git to make git behave like a blob
store; it could take only one writer, since two machines force-pushing one root erase each
other; and at 1.9 GB it was heading past what GitHub advises. The move (`keel backup
migrate`; the repo it names is `[backup] legacy_repo`, exported as `KEEL_BACKUP_LEGACY_REPO`,
since no repo name is tracked after c-610 S1) copied every retained snapshot across, re-encrypted the helm set under its own
key, and ran the ordinary store verify for every set before anything switched. It was
rehearsed on 2026-09-19 against the real GitHub clone into a scratch store: 45 keel, 176
harbor and 32 helm snapshots, all three read back.

## Four sets, and who writes them

A set is a root on disk, a place in the store, a file list, a retention policy, a canary
that proves a restore unpacked the right tree, and its own alarm key. They share one store
and one lock and nothing else.

| Set | Root | Written by | What it is |
|---|---|---|---|
| `keel` | the install's home: the parent of the config's state dir (`~/shipyard`) | the machine whose `[backup] sets` names it | the board, every card directory, every blackboard under `state/boards/` ([the board](45-board.md)), the voice data, every segment's data, the install's `config.toml`, and its `memory/`, `identity/`, `packs/`, `history/`, `spaces/` and Claude memory, with `repos/<name>.bundle` for each install repo's history (c-722, c-725) |
| `code` | the checkout, `$KEEL_HOME` (`~/keel`) | with `keel` | `code/keel.bundle`: a `git bundle` of every branch and tag of the checkout |
| `harbor` | `~/harbor` | the machine whose `[backup] sets` names it | the old engine's segment data and ledgers, frozen |
| `helm` | `~/.claude` | the machine whose `[backup] sets` names it | the retired PR tools' history, read-only: the review scanner's `pr-reviews` whole (state, findings, orientation notes) and PR watch's `pr-watch/context` (context notes, `_archived`, the `_assets` screenshots). The watcher's own caches are not copied since it retired (lane RETIRE) |

**Keel's own sets are `keel` and `code`** (`config.BACKUP_SETS`, c-722); a new install
names only those. `harbor` and `helm` are one install's own: its config names them under
`[backup] extra` beside `sets`, `keel backup env` hands them to the tool as
`KEEL_BACKUP_EXTRA`, and the tool's known sets are its own two, the extra ones, and any
other its `sets` names, so a config from before `extra` backs up, restores and pulls as it
did, with no new line in the doctor. The tool has facts for those four sets and no other
(`config.TOOL_SETS`): a name in `sets` or `extra` outside them is refused where the config
loads, so no job is ever handed a set it would die on. `shipyard move-personal` writes
`extra` from the sets a checkout's `keel.toml` names, and nothing else of `[backup]`
([install](88-install.md)). The two sets' per-set facts stay in the tool by name until a set
can be described by the config alone.

**The keel set is the install's board** (c-622). `keel backup env` hands the tool the
config's state dir (`KEEL_BACKUP_STATE_DIR`), and the set's root is its parent, so an
install whose board is `~/shipyard/state` is backed up from there while the jobs run from the
checkout at `~/keel`. The jobs read the config `keel backup install` was run with
(`KEEL_CONFIG` in their environment). A state dir not named `state` is refused (the archive's
paths are `state/...`), and so is a state dir with no board once the set has history: a
board-less snapshot published over good ones is the empty-snapshot failure again. Since
c-622 one machine writes every set. An older checkout's `keel.toml` shipped code, harbor and helm:
its state dir is not the install's board, so a job reading it with keel listed would refuse
every hour. keel is named in the install's own config, whose `[backup] sets` the jobs read
once `keel backup install --load` is run with `KEEL_CONFIG` pointing at it.

**One set has one writer.** Which sets a machine writes is `[backup] sets` in its
config, and whether it pulls is `[backup] pull`. A file written for two machines kept both
under `[hosts.<this host>]` as `backup_sets` and `backup_pull`; they are still read from
there while `[backup]` does not say, so an old file keeps backing up. `latest.json` names
the host that wrote it, and a machine that finds another host wrote the set within the
last 24 hours refuses to write it at all, unless told `--take-over` (for a set that has
really moved to this machine). Two
writers would each prune by retention and each publish a `latest.json` the other's change
test then disagrees with, forever.

**Retention is decided on the store's ids**, not on anything local, so a machine taking a
set over, with none of its history on disk, cannot prune the other machine's snapshots as
"not retained". Every set keeps each snapshot of its hourly days, then the newest of each
day to its daily days, then the newest of each month, and the newest snapshot of all
whatever its age (`set_hourly_days`, `set_daily_days`, `retained_deletions`):

| set | every snapshot for | one a day to | beyond | floor between snapshots |
|---|---|---|---|---|
| `keel` | 1 day | 30 days | one a month | none |
| `code` | 1 day | 30 days | one a month | 6 hours |
| `harbor` | 7 days | 90 days | one a month | none |
| `helm` | 2 days | 30 days | one a month | 6 hours |

**`keel` keeps a day of hourly snapshots and thirty of dailies** (c-752, the owner's
decision of 2026-10-12; it was 7 and 90, as `harbor` still is). Measured on 2026-10-11, the
store held 13.2 GB and almost all of it was the last week's hourly snapshots of this set:
94 of them from 5 to 9 October, 10.9 GB, each a full copy of about 115 to 130 MB, with
everything older 1.1 GB together. At 7 and 90 the store settles at 20 to 30 GB whatever
else is done; at 1 and 30, near 7 GB. Same-day recovery stays, and past a day the day's
last state is the one a restore wants. `tests/test_backupretention.py` runs the hourly job
over a made-up listing and reads what the store still holds.

**A change of retention takes effect at the next run**, and there is no other deletion
code: the next run that publishes a snapshot prunes by the rule above with the new
numbers, in one pass, however many snapshots that is (a run that finds nothing changed
publishes nothing and prunes nothing). What it drops goes to the store's trash for 30
days where the store has one: Drive does, a `file:` directory does not, and there the
snapshots are gone at once. So the space on Drive comes back a month after the change.
One thing retention never reaches: where a slim rewrote a snapshot and kept its old
archive, that archive sits under `slim-old/<set>/`, outside the set, and stays there when
the snapshot is pruned. Those go only with `keel backup slim --purge`, which is when
their space is freed (into the same trash).
The slim asks the same rule (`slim_retention_list`), so it agrees from the same moment,
and the mirror is unaffected: it keeps the newest snapshot of each of the 3 most recent
days, which every set's dailies still hold.

`helm` has a floor of one snapshot every 6 hours. The floor was there because the watcher rewrote a status timestamp every few
minutes and the content test could never skip the set; with those status files out of the
set it is history that does not change, so the content test skips it and the floor is the
second guard. `code` keeps 1 day hourly and 30 daily, with the same 6-hour floor: a
bundle is 17 MB against keel's 8 MB, every commit on any branch changes it, and a restore
only ever wants the newest.

**helm has its own passphrase.** keel and harbor share "Shipyard backup passphrase" (a key
saved before c-729: "Keel backup passphrase"; `key_name` is what a new key is saved as,
`key_was` names both wherever the user is asked to find it); helm uses
"Keel backup passphrase (helm set)". Whoever holds the store's login can fetch every
object in it (one Drive app, one user: there are no per-folder keys), so the key, not the
store, is what keeps employer review notes out of reach of a machine that has the login but
not that passphrase.

They are separate sets rather than one archive because **restore is the test**. The roots
are different places on disk, so one archive would need synthetic prefixes and
`restore --into DIR` would unpack all of them whichever one you came for. Per set also
means the change test, the retention and the alarms are per set, and an alarm that one set
can retire on another set's behalf is an alarm that erases itself.

## What is in the keel set, and what is not

In: `state/`, `segments/*/data`, the install's own `config.toml` when there is one
(c-610 S1: it is untracked, so the code set never carries it, and a restore without it
would come back on the shipped defaults), and the install's own things that left the code
in c-722: `memory/` (Bosun's and the talker's memory, the talker's rulebook), `identity/`
(the user's profile), `packs/` (the install's own packs, the work pack among them) and
`history/` (the design notes and old Atlas pages the move carried), and `spaces/` (a
space contract of the user's own) and the install's Claude memory, `claude/projects/*/memory`
(c-725 r1.F6). The code set's bundle held the first four while the checkout tracked them;
since they left the tree nothing else holds a copy. Their `.git` directories stay out like
every other, and the history of each install repo with a commit (`memory/`, `packs/`) rides
instead as a git bundle, `repos/<name>.bundle`, rebuilt only when a ref moved (r1.F8). A
restore puts the files back at the same paths under the install's home, beside `state/`.

Out, each on the same question, what does losing it actually cost:

- `state/logs/`, which is a record of how the state got here rather than the state, and
  grows on every poll.
- `state/worktrees/`, every byte of which is reachable from the repo's own history.
- `state/drafts/`, scratch work: demo films, audio stems, prototypes. One
  demo-video pass can put about 1.2GB of mp4 and wav there and take every hourly snapshot from
  26MB to 173MB. A draft worth keeping is promoted into a card or a repo.
- A card's `scratch/` folder, whole: `state/cards/<id>/scratch` and everything under it
  (c-752, the owner's decision of 2026-10-12). Scratch is by name the place for throwaway
  copies; what a card must keep belongs in its folder proper, and anything a house leaves
  in `scratch/` is not backed up. The rule before this one dropped only a first-level
  directory there that held `.git` and kept the rest. Measured on 2026-10-11, one done
  card (c-512) had three plain copies of a product repo's source in its scratch, with no
  `.git`, so that rule archived them every hour: 104MB of a 302MB snapshot. Only the
  card's own `scratch/` is named: a deeper folder of that name (`out/scratch`) stays in.
  `tests/test_backupscope.py` snapshots a card with such a folder and restores it.
- `node_modules/`, anywhere under the roots. A card's scratch checkout of webapp-react
  (c-512) carried 418MB of it into every snapshot; `npm install` rebuilds it.
- Video and audio files (`*.mp4`, `*.mov`, `*.webm`, `*.wav`, `*.m4a`) anywhere, a card's
  `out/` included. After drafts were dropped, a 138MB demo film in card c-568 still kept every
  snapshot at 176MB. A recording worth keeping lives on Drive or in a repo.
- `state/fetch-locks/`, held only while a fetcher runs. A restored lock is a lock nothing
  will release.
- `state/boards/.attached/`, where a board file waits between the attach that carried it and
  the push that names it ([the board](45-board.md)). Pruned after an hour, and a restored one
  is a file nothing will ever push. A board's own copies, under `board-files/` and `files/`,
  are IN: they are what the record shows. So is `state/boards/.trash/`: a board the user deleted
  is restorable for 30 days, so it is carried until the drain purges it, and a restore from
  the archive brings the trash back with it (BD-4).
- `state/human.token` and `state/artifact.key`. Credentials never leave this machine,
  encrypted or not. A Google TTS key follows the same rule from outside the set:
  it lives in `~/.config/keel/credentials/`, never under `state/`, and a restored machine gets
  it back by `keel voice key set` ([voice](50-talker-and-voice.md)).
- `state/talker.pid`, which names a process on this laptop.
- `merged-tests.log`, anywhere in the set (the landing writes it into the card's
  directory), the whole output of a landing's test run
  ([cards and gates](10-cards-and-gates.md)), about 0.9MB a card. A log is not state, the
  same rule that keeps `state/logs/` out. Measured on 2026-10-06 (c-594) they were 67MB of
  the 264MB a snapshot holds, re-archived every hour (c-671). The file is named exactly,
  not as `*.log`: another log in a card's directory may be the card's evidence, and stays in.
  After a restore a refusal's text may still name the log: the deck shows no link to it,
  and approving again reruns the suite and writes a new one.
- `state/voice/cache/`, the TTS clip cache: regenerable by saying the line again, and most
  of the tree by size. Including it would re-archive it in full on every real change
  anywhere, which is exactly the scope fault that took the old repo past a gigabyte.
- `state/voice/pcm/`, the recorded utterances the end-of-utterance hangover is measured on
  ([voice](50-talker-and-voice.md)). The one entry here excluded for WHAT IT IS rather than
  what it costs: it is recordings of the user talking, kept for a few days and then deleted
  by `keel voice corpus --delete`. An archive is the one copy nobody goes back and deletes,
  so they never enter one. On disk they are 0600 in a 0700 directory, which is the
  recorder's own guard rather than this file's, but it is the same reasoning.

**The board is staged, not scanned.** `state/board.db` is a live WAL database that the
drain, the deck and the talker all write to, so a file-by-file copy of it is a torn read.
The scan skips `board.db` and its `-wal` and `-shm`, and a consistent copy taken through
sqlite's own online backup API is appended to the archive at that same path. The canary
for this set is that file, checked by opening it and counting its cards: a board that
unpacks but holds nothing is the failure worth refusing over.

## The code set

In: one file, `code/keel.bundle`, a `git bundle` of every local branch and tag of the
checkout at `~/keel`, staged the way the board is. Nothing is read off the working tree:
uncommitted work is not code yet, and the worktrees' branches are in the bundle.

**It is rebuilt only when a ref moves.** The list of refs and the commits they name is
hashed, and the bundle kept under `~/.keel-backup/work/code/bundle/` is reused byte for
byte until that hash changes, so a quiet hour is an unchanged manifest rather than a bet
that git writes the same pack twice. A home that is not a git checkout has nothing to back
up, and the empty-manifest rule decides whether that is a quiet hour or a loud one. The
canary is the bundle, read by `git bundle list-heads` and required to hold `main`.

## The second copy: the nightly pull

`keel backup pull` runs on a machine whose config says
`[backup] pull = true`. It copies into `~/.keel-backup/mirror/` the recent end of
every set whoever writes it (see "It holds only the recent end" below), each object checked
against the store's md5, and then proves the newest snapshot of each set it holds a key for by
decrypting it and checking its canary. So this machine vanishing costs nothing the store did not
already hold, and the store vanishing (a lost Google account, a writer gone wrong) costs at
most a night.

**When it runs: when it is due and the machine is awake** (c-440, 2026-09-23). It used to run
only at 03:00, and a laptop asleep then does not skip the job: launchd starts it in one of
the Mac's DarkWakes (a few seconds awake, every fifteen minutes or so), and the process sits
frozen between them, so the pull finished six hours later, the morning the lid opened. Now
the drain starts it (`backup.pull_upkeep`, see [the drain](30-drain.md)) once the
last good pull is more than 20 hours old, detached, under `caffeinate -i`, at most once an
hour, with its output appended to `pull.out` and `pull.err` as the job's would be. A drain
only passes while the machine is awake. The 03:00 job is still installed as a backstop, and
the pull's own lock (`.pull-lock`) keeps the two from running at once; retiring it would be
a launchd change (`keel backup install --load` after dropping it from `installed_labels`),
which is the user's to make.

**The commit point goes last, and is judged the way the store judges it.** The pull lists
the store once and then copies for as long as it takes, while the writer rewrites each set's
`latest.json` every hour. Checking that file against the listing's md5, as every blob is
checked, failed every long pull on exactly that one file, two nights running, with every
blob already copied. So `latest.json` is fetched per set after every blob, and accepted when
it parses and the snapshot it names is in the mirror. When it names one the mirror lacks
(the writer published mid-pull), the set is listed once more, what is new is copied, and it is
tried once more; a `latest.json` that still names nothing the mirror holds is never written,
and the mirror keeps the commit point it had. `bin/keel-backup-selftest` proves it with a
stand-in writer rewriting `latest.json` as fast as it can for the length of a pull.

**Its notice says the same thing every hour.** The hourly job re-states an open
`backup-pull-stale` notice, and its brief used to carry a relative age, so every hour was a
new `kb set` event on the card. The brief now gives the last good pull as a timestamp, quotes
the last pull's error from the state file, and names `pull.err`, which is where the error is
written (`pull.out` ends with the last success). `Board.set_fields` also records nothing for
a set that changes nothing, whoever calls it.

**It holds only the recent end** (2026-10-01). The store keeps the full hourly and daily
history; the mirror is the copy for the store vanishing, and for that the newest state is
what counts. Per set it keeps the newest snapshot of each of the 3 most recent days
(`KEEL_BACKUP_MIRROR_DAYS`), fetches only those and drops the rest. Holding every hourly
copy had taken it to 15GB on a 228GB disk.

**It never deletes because the store did.** A copy that mirrors deletions is a copy a bad
writer empties in one night. The keep set is computed on the union of the mirror's own ids
and the store's listing, so a snapshot the store loses stays in the mirror until three newer
days have replaced it. The mirror has the store's own layout: `file:~/.keel-backup/mirror` is a store, and
`restore --local` and `verify --local` read it.

## The rules that shape the tool

1. **Nothing it writes lands inside a checkout.** The passphrases, the store's login, the
   state file, `work/`, `mirror/` and the logs are all under `~/.keel-backup`. An
   untracked file inside a checkout dirties the tree, and this runs every hour.
2. **The change test is on plaintext.** `gpg` output is nondeterministic, so hashing the
   ciphertext would report a change every hour forever. The manifest hashes each file's
   content, and a run whose digest matches the store's `latest.json` is skipped, which
   counts as a successful run rather than staleness.
3. **Every write to the store is proven by the store.** The md5 it lists, not an exit code.
4. **The keys have to leave the machine.** A passphrase stored only on the disk being
   backed up is a decoration. Generating one stages a card carrying it, and a missing
   keyfile beside an existing history refuses to run rather than silently orphaning every
   snapshot behind a new key.
5. **Failure is loud, and each alarm has its own key.** `backup-stale` (new data is not
   reaching the store: a run failed, or none has run, which only the drain can see, below), `backup-unreadable-<set>` (what is there cannot be read back;
   harbor's is the bare `backup-unreadable`), `backup-public` (something in the store is
   shared beyond the user's account), `backup-auth` (the store refused the login),
   `backup-pull-stale` (the nightly copy is two nights late, or does not read back) and
   `backup-size` (past 8 GB). They mean different things and are fixed by different
   actions; sharing a key once let the hourly job retire the weekly one. An alarm is only
   retired by a run that proved as much as the one that raised it: a local verify retires
   nothing, a narrowed `--set` run moves no run-wide clock, and `backup-public` retires only
   on a literal "nothing shared", never on an unanswered question.

6. **Nothing that should have happened may pass for a quiet hour.** A snapshot that never
   reached the store waits in `pending/`; a blob with no proof beside it is discarded, never
   published; a set whose root is gone while the store holds its history fails the run;
   and settings that cannot be read (`keel backup env` failing) fail it too, rather than
   reading as "this host writes nothing".

A notice is an ordinary card: personal, attended, topic `notice`, carrying
`options.notice_key`, open until it is staged `done`. That is the one store rule holding:
the alarm has nowhere else to go.

**A notice retires itself, and says so when it cannot.** `queue close K` stages the open
card under K `done` from inbox, which the board allows for a notice and nothing else (J-1).
Until then the board refused it and every `clear_*` ended in `>/dev/null 2>&1 || true`, so
not one notice had ever retired: the selftest's stub board took any stage and hid it. Every
`clear_*` now goes through `close_notice`, which treats 5 (nothing open under the key) as
the ordinary answer and says any other failure in the log, with the board's own refusal on
stderr. `bin/keel-backup notice add|close ...` runs the same `queue` function by hand, and
`tests/test_notices.py` drives it against a real board through the real `bin/kb`.

## When the hourly job stops: the drain's watch (c-750)

The staleness alarm above is raised by `status --announce`, which the hourly job runs at
the end of each run. So it can say that runs are failing, and it cannot say that runs have
stopped: a job nothing starts raises nothing. That happened (below), and the backup sat 33
hours old with no card, a clean state file and a job whose last exit was 0.

The drain is what sees it now (`keel/backupdue.py`, called each pass as
`drain.snapshot_upkeep`). It passes only while the machine is awake, and the deck's health
goes red when it stops passing, so it is watched itself. Where the config names a store and
at least one set, each pass reads `last_success` from the tool's `state.json` and:

- **Starts an overdue run.** Past the hourly interval plus 15 minutes
  (`MARGIN_SECONDS`), with no live process holding the tool's lock (`.lock`), it starts
  `bin/keel-backup snapshot`: detached,
  under `caffeinate -i`, with the environment and the settings `keel backup` hands the
  tool, its output appended to `backup.out` and `backup.err` where the job's goes
  (`backup.start`, which the nightly pull's start and the first copy of a backup just
  turned on use too: the one way Keel starts a run itself). The success it measures from
  is this install's own (`backupdue.own`, by `backupstatus.own_stamp`, c-757 review r1.F6):
  on a second install on the account, the first one's recent `last_success` is no success
  here, so its first copy is owed at once and not held at "not due" for an hour. The tool's own lock is what
  keeps two runs apart: a run started while another holds it says so and exits 0 ("The
  lock", below). A backup that has never succeeded is overdue too.
  **Never on one pass alone** (review r1.F2): two passes in a row, the second inside five
  minutes of the first (`AWAKE_PASSES`), so the first pass after the lid opens, when the
  network may not be up yet, starts nothing and the next one, half a minute later, does.
  **A run that ended with no success is tried again ten minutes later** (`RETRY_SECONDS`),
  once its lock is free, and the drain starts at most three in an hour
  (`STARTS_AN_HOUR`). A run with no network dies in seconds and files the tool's own
  "Keel backup failed"; waiting the whole hour to try again left that card standing for
  an hour over a ten second fault.
- **With the lid closed, plainly.** A closed laptop wakes by itself in DarkWakes. In a
  short one the drain gets one pass, or none, and that starts nothing. In a long one the
  drain passes every half minute as if the lid were open, and there it does start the
  snapshot, under `caffeinate -i`, which holds the machine awake until the run ends: a few
  seconds when nothing changed, minutes when there is something to upload. On a night like
  the one below that is a run in each of the two long stretches, about one an hour while
  they last. If such a run fails, the tool's failure card is on the board in the morning
  unless a later run that night succeeded and retired it. That is the price of the backup
  not waiting for the lid: the same choice the nightly pull made in c-440.
- **Counts waking time.** Once a run is owed (the last success is over an hour old) it
  adds up the time the drain was passing, in `~/.keel-backup/snapshot-watch.json`. Two
  passes more than five minutes apart (`AWAKE_GAP_SECONDS`) are a machine asleep, or a
  drain stopped, and the gap counts for nothing. **The gap is the larger of five minutes
  and a poll and a half of the drain's `poll_seconds` plus a minute**
  (`backupdue.awake_gap`): a drain set to poll every 400 seconds never has two passes
  inside five minutes, and with a fixed gap it counted nothing and its two-pass gate never
  opened, so no overdue run was ever started. At 400 the gap is 660 seconds, so its own
  passes count and single passes fifteen minutes apart still do not. The same gap is the
  one the two passes of a start must fall inside. Two things it does not cover. Slow
  passes: a minute is all a pass is allowed, so a drain whose passes run for many minutes
  at a small `poll_seconds` falls outside the gap and counts and starts nothing. And a
  `poll_seconds` of 560 or more puts the gap at fifteen minutes, which is how far apart a
  sleeping Mac's DarkWakes come: from there up a drain's ordinary passes and one pass per
  DarkWake cannot be told apart, and a night asleep is counted as awake. **This is how sleep is told from a silent
  stop:** Keel had no reading of when the machine woke, and the drain's own passes are one
  it already has, so a laptop closed overnight is nine hours older in the morning and not
  nine hours overdue. A short DarkWake (a few seconds awake, every fifteen minutes or so)
  adds at most the seconds between two passes inside it. A long one counts, and should: a
  closed lid is not always a sleeping machine (on the night below the drain passed for 78
  and then 58 minutes on end with the lid shut), and a drain that is passing can start a
  run, so time it passes with no success is time a backup was owed and did not happen.
- **Says so, once.** When the count reaches two hours (`OVERDUE_SECONDS` less the first
  hour, in which no run was owed), which is three hours after the last success on a
  machine awake throughout, it files one notice under the tool's own `backup-stale` key:
  "No backup has succeeded in over 3 hours", with the last success as a timestamp and the
  log's path. One key on purpose, by the rule above that staleness is one alarm: a notice
  the tool already raised under it (a run that failed) is the one notice, and none is
  added. It is filed once per missing success, so a card tapped away stays away, and never
  while a run holds the lock: a first copy or a big upload can outlast two waking hours,
  and the card waits for it to end. **The run comes before the card:** the pass starts
  its run first and files the card after, in a guard of its own, so a board that will not
  take the card costs the card (logged, sighted for Bosun, tried again next pass) and
  never the backup. **The
  next run that succeeds retires it**, as it retires its own (`clear_broken`); the drain
  never closes a card, because a `backup-stale` card can also be a failed run's, raised
  while the last success is still fresh. A success also deletes the watch file, so the next
  count starts from nothing.

`keel doctor` prints a `backup` line with the last good run as the tool stamped it, or
"not set up here", and a snapshot the drain has counted overdue is a problem, in the
count's own terms: "no successful run since `<stamp>`, and over 2h awake with one owed"
(two waking hours with a run owed is what the count holds; it is three hours since the
success only on a machine that never slept). It reads the watch file and writes nothing,
so a doctor run just after the lid opens does not call a night's sleep a fault.

The watch file sits beside `pull-kicked` in `~/.keel-backup`, outside every set. It is the
drain's memory of one machine's waking time, not board state, and nothing has to agree
with it: delete it and the count starts again. Nothing in it can stop a pass either:
garbage reads as an empty watch, and a field of the wrong type as a field not there
(`backupdue.read`). The one thing that does stop the watch is a home the file cannot be
written to: then no run is started, because nothing would bound the starts and the tool
could record no success there, and the step fails in the drain's log on every pass.

The watch is the first step of the drain's pass, before anything that can raise, so a
pass that fails further down has still counted and still started its run.

### The lock

Three things start the tool by themselves or by hand: the scheduled job, the drain, a
person. `lock_take` in `bin/keel-backup` keeps them apart, for the snapshot (`.lock`) and,
through the same function, for the nightly pull (`.pull-lock`).

- **The lock is a symlink whose target is the holder's pid**: `ln -s <pid> <lock>`. One
  step makes it and signs it, and it fails when anything is at the name, so a lock is never
  there without saying whose it is. The link points at nothing and is only ever read with
  `readlink`. `keel/backup.py` `lock_live` reads it the same way for the drain.
- **A live pid holds it**: the run stands down, exit 0, however old the lock is.
- **A dead pid's lock is broken once it is half an hour old** (the link's own mtime), by
  renaming it away, so of two runs that judged it stale only one rename finds it. The
  breaker reads what it renamed: if that names another pid than the dead one it judged, it
  renamed a live run's fresh lock, makes it again for that run and stands down.
- **A run removes at the end a lock that names it, and only that.** The lock says whose
  it is, so release asks nothing else: a run stopped the instant after it made its lock
  still takes it away with it.
- **Failing to make the lock for any other reason is a failed run**: `ln` failed twice and
  the name was free both times (a full disk, a home that cannot be written). Twice,
  because once is also what a lock released in between looks like. It exits non-zero and
  files "Keel backup failed", as any failure does.
- **A directory at the name is the older lock** (a directory with a `pid` file, signed a
  step after it was made), left by a run of the tool as it was, across a deploy. It is read
  by its pid file under the same rules and a stale one is broken the same way; the tool no
  longer makes one.
- **What a breaker killed half way leaves**, `<lock>.stale.<its pid>`, is swept by the next
  run once that pid is gone and it is a minute old.

**What remains.** One case in which two runs go on at once: two runs break the same stale
lock, the second renames the first's fresh lock by mistake, and a third run takes the name
in the milliseconds before it is made again (or the second is killed in them, and a run
comes later while the first still works). The first then runs with no lock at the name.
Closing it needs a rename that tests what it renames, which the shell does not have. The
comment in `lock_take` walks the interleavings, and `tests/test_backuplock.py` makes each
of them happen against the real tool, through a command of the test's own that gives
another run one turn at a named point.

### What was seen on 2026-10-11 (observed, read only)

The owner's Mac, macOS 27.0 (26A428), up 13 days. All times UTC; the Mac's own are +05:30.

- `~/.keel-backup/logs/backup.out` has a run ending `2026-10-09T19:35:46Z` and then
  nothing until `2026-10-11T05:30:48Z`: 33 hours 55 minutes. `state.json` held
  `last_success` `2026-10-09T19:35:45Z` and `last_error` `""`. `backup.err` was last
  written on 2026-10-05.
- Before the job was started by hand, `launchctl print gui/501/dev.keel.backup` showed
  `state = not running`, `runs = 103`, `last exit code = 0`, `job state = exited`,
  `run interval = 3600 seconds` and `pended nondemand spawn = interval` (as reported on
  the card by the person who looked; not seen again afterwards).
- A `launchctl kickstart` at 05:30:41Z ran it at once. launchd's own log
  (`/var/log/com.apple.xpc.launchd/launchd.log`) has that start as "launching: non-ipc
  demand" and its end as "exited due to exit(0), ran for 341297ms". Afterwards
  `launchctl print` showed `runs = 104` and no `pended` line.
- `pmset -g log`: the lid closed ("Clamshell Sleep") at 2026-10-09T20:26:06Z, 50 minutes
  after the last run and about 9 minutes before the next was due. 27 DarkWakes followed
  overnight. A full wake ("Wake from Deep Idle", lid and keyboard) came at
  2026-10-10T05:43:09Z, and the log has no sleep entry after it up to the kickstart. So the
  machine was fully awake for 23 hours 47 minutes with the hourly job never started.
- With the lid closed that night the drain's log (`state/logs/drain.log`) still has
  passes every half minute from 2026-10-09T22:27Z to 23:45Z and from 2026-10-10T01:25Z to
  02:23Z, and a few single ones between. The hourly job ran in none of those stretches.
- The same Mac slept with the lid closed twice earlier on 2026-10-09 and the hourly runs
  carried on after both: asleep 07:00 to 07:35Z, next run complete at 08:36Z; asleep 14:46
  to 15:26Z, next run complete at 15:28Z, two minutes after the wake. The log shows the
  same through 2026-10-08: a run about every 62 minutes, with a longer step across a sleep.
- The two calendar jobs ran through the gap: the nightly pull (`last_pull`
  `2026-10-10T21:30:36Z`) and the weekly verify (`last_verify` `2026-10-10T23:01:26Z`).
- `launchctl print-disabled gui/501` lists no `dev.keel.*` or `dev.shipyard.*` label, so
  the job was not disabled.
- The same day launchd held a newly bootstrapped service's first start with
  `pended nondemand spawn = speculative` (c-747).

What could not be read: why launchd held it. launchd's log file rotates in under an hour on
this machine (its three files covered 50 minutes), so nothing from the night of the 9th was
left, and `log show` for process `launchd` naming the label returned no lines for that
night. Nothing was loaded, unloaded, started or edited to find out.

### What is guessed, not known

- The interval timer came due while the lid was closed, launchd pended the start for the
  wake, and the pended start was never released: `pended nondemand spawn = interval` is
  launchd's own word for a start it is holding, and the gap begins at the first interval
  that fell inside a sleep. Against it: the same thing did not happen after the two
  earlier sleeps that day. What differed that night is its length: over nine hours and 27
  DarkWakes, against 35 and 40 minutes.
- The hold belongs to this macOS release rather than to the job: the other hold seen the
  same day (`speculative`, c-747) was on a different service with a different plist.
- Whether the job resumes by itself after a kickstart, and whether a calendar schedule
  (which launchd runs once on wake, and which the pull and the verify use) would have
  been held too, is not known. Neither was tried: changing the job is the owner's to do.

None of this is needed for the watch above, which does not depend on why a run did not
start. One consequence of what was seen is not a guess: the drain passes in a long
DarkWake, so on a night like that one it now starts the snapshot there, under
`caffeinate -i`, as it has started the nightly pull since c-440.

## Getting the data back

```
keel backup verify                      the weekly proof, by hand
keel backup run --force                 a snapshot even if nothing changed
bin/keel-backup restore --into ~/scratch/restore             the keel set, from the store
bin/keel-backup restore --set helm --into ~/scratch/helm     another set
bin/keel-backup restore --local --into ~/scratch/restore     from the mirror instead
```

`restore` reads the STORE by default, because the question a backup answers is whether the
copy that survives this machine is readable, not whether a local one is. It refuses a
destination inside the live checkout: unpack into a scratch directory, look at it, then move
what you want into place. Nothing here is a merge. [Restore](86-restore.md) is the whole runbook for a
machine that has lost everything.

## Slimming the old snapshots (c-724)

A scope fix only slims the snapshots taken after it. The ones already in the store keep
what the scan dropped later (drafts, `node_modules`, films, a landing's test log, a card's
scratch folder), each a complete copy, for as long as retention holds them: about 15 GB on
2026-10-10, nearly all of it things the backup had already stopped carrying. `slim` rewrites
them in place. It deletes no snapshot, changes no id and touches no retention rule, and it
keeps every archive it replaces until told to purge.

```
keel backup slim --dry-run --set keel --limit 3    read three, say what would go; writes nothing to the store
keel backup slim --dry-run --set keel              the same for every snapshot not yet slim
keel backup slim --approved --set keel --limit 1   rewrite one of the snapshots the dry run showed
keel backup slim --approved --set keel             rewrite the rest of them; run it again after a stop
keel backup slim --restore <id> --set keel         put a rewritten snapshot's old archive back
keel backup slim --purge --set keel                remove the kept old archives; only now is space freed
keel backup slim --purge --unproven <id> --set keel   remove one object under slim-old/ that is nobody's old archive
```

There is no bare rewrite: `slim` with neither `--dry-run` nor `--approved` refuses and says
both. It does one thing at a time: more than one of `--dry-run`, `--approved`,
`--restore` and `--purge` is refused, and an id given to it must be a snapshot id
(`20260901T000000Z`) or it dies before anything is touched (r3.F9: an id is spliced into
the store's keys, and one with `../` in it named a real snapshot on a folder store). `--set` names one set (every set this host writes otherwise; a rewrite is a write, so
only a set's writer rewrites it, while a dry run may read any set it holds the key for).
`--limit N` examines only N snapshots, oldest first. `--json` prints the report as one
document. The verb is the tool's (`bin/keel-backup slim`); the arithmetic is
`keel/backupslim.py` with `keel/backupslimapproval.py`, `keel/backupslimjournal.py` and
`keel/backupslimreport.py`, which the tool calls. The tests run all of it against a
scratch store, a module a concern: `tests/test_backupslim.py` (the dry run, the rewrite,
the sums), `test_backupslimapproval.py`, `test_backupslimrecovery.py`,
`test_backupslimrollback.py` and `test_backupslimlocks.py`, on the fixture in
`tests/backupslimcase.py`.

**What is dropped is decided by the scan itself.** The snapshot is unpacked, and the set's
own file and directory lists (`keel_find` and its siblings, the one place the scope is
written) run over the unpacked tree exactly as a snapshot runs them over the live one. What
they list is kept. So is every path the set stages rather than scans (`set_staged`, beside
`set_stage`: the board and each repo's bundle for keel, the bundle for code; r2.F12), kept
by name wherever it sits, and so is anything under none of today's roots, which no rule
names. The rest
is dropped. There is no second list. The rule names in the report are read out of the
find's own text, so a rule added there is named with nothing else to edit. A set whose scan
leaves nothing out (`code`) is skipped whole.

**The rewrite does what the dry run showed, and nothing else** (r1.F2). The dry run writes
what it showed to `~/.keel-backup/slim-approved.json` (local, beside the keys, never in the
store): per snapshot, the md5 of the object it read, a digest of everything that decides a
drop (`set_decides`: the find, the roots and list functions, the staged paths, the
canary's name; the functions as the tool's own file writes them, read out of it by
`fn_source`, not as one bash prints them back, so another bash gives the same digest, r3.F7.
**The digest is of the text, comments and spacing included**: any edit inside those
functions, a comment too, is a change of rules to it. That fails safe and is left so, at
this cost: after such an edit the approval file covers nothing until a new dry run, and
every snapshot already slimmed counts as slimmed under older rules and is fetched and
read again), a digest of the dropped paths themselves and of the roots it found, sorted (r2.F2:
equal sums by rule are not the same files), and what it would drop by rule. `--approved` refuses a snapshot that file does not cover exactly:
one the dry run has not shown is not even fetched; one whose object changed, or whose
rules changed, is refused; and one whose plan drops anything more, less or different than
was shown is refused before anything is packed. Each says to run the dry run again. A run
in which every snapshot it came to was one the dry run has not shown exits non-zero and
says to run the dry run, and an approval file that is there and does not parse stops the
run before any snapshot is judged on it (r2.F8): damage is not an empty file. A
snapshot the dry run found nothing to drop in is marked in the journal with no second
fetch. So a rule added to the scan between the reading and the rewrite cannot widen what
is permanently dropped.

**An archive answers every rule by itself, and `--live-git` is gone** (c-752). `.git` has
never entered an archive, so an unpacked snapshot cannot answer a rule that asks whether a
directory holds one. For three days one rule did (c-724, 2026-10-09 to 2026-10-12: a
directory of a card's `scratch/` holding `.git` was dropped), so a dry run told
`--live-git` asked the live tree, marked the unpacked directories whose live ones were
checkouts, and recorded them in the approval file for the rewrite to mark again. c-752
leaves a card's `scratch/` out whole, which the archive's own paths answer, so no rule
asks about `.git` and the flag, the marking and the approval's `live` list were removed
rather than kept unused: code that can drop backup content and that nothing exercises is
worse than none. The design is in c-724's history (its r1.F6) if a rule ever needs it
again. `--live-git` is now an unknown argument. An approval entry from before that names
trees in `live` is refused with "run the dry run again"; so is every entry written under
the old scratch rule, because the rules' digest changed with it
(`tests/test_backupslimapproval.py`). For the same reason a snapshot slimmed under the
old rule is looked at again by the next dry run and loses the rest of its scratch.

**One snapshot at a time.**

1. It is fetched (proven by md5), decrypted and unpacked, and the unpacked tree must be the
   archive path for path: the archive's own member list is read and compared with it
   (r1.F3). A `._name` member is left out of that comparison only when it is AppleDouble
   by its first four bytes, its `name` is a member too, and the tree does not hold it:
   macOS tar writes a file's extended attributes that way and folds them back in. Any
   other `._name` is a file (r2.F7; measured on macOS 27, bsdtar 3.5.3: a `._x` that is
   not AppleDouble makes tar exit 1 in any order, so such a snapshot is left as it is).
   Every later proof compares unpacked trees, so a path lost in unpacking (two
   names a volume folds into one, a directory that cannot be listed) would otherwise be
   lost from the rewritten snapshot with every proof passing. Then it is scanned. With
   nothing to drop, the journal says so and the object is never written.
2. It is packed again from the unpacked tree, encrypted under the same key, decrypted and
   unpacked once more, and proven: the same files with the same content, mode and time,
   the same directories with the same mode and time, minus exactly what was dropped, and
   the canary still reads. Times are compared to the nanosecond on macOS, whose tar
   carries the fraction, and to the second where tar is GNU's, whose default format does
   not (r1.F10). A
   snapshot that fails any of it is left as it is, and the run says which and why.
3. Under the backup's own lock: the store must still list the snapshot as it was fetched
   (one retention pruned meanwhile is never put back). The old archive is copied to
   `slim-old/<set>/<id>.tar.gz.gpg` and proven there. The new archive is put under a
   temporary name, `slim-tmp/<set>/<id>.new`, and proven there by the store's md5. Both
   are outside `sets/`, so no pull mirrors them. The journal records the replace. The new
   archive is put over the old one's name and proven by md5. A `latest.json` that names
   the snapshot is made to describe what it now holds, so the hourly change test still
   skips an unchanged tree. The temporary object is removed and the journal says done.

**The put over a name is not assumed to be all or nothing** (r1.F5). On a folder store it
is a rename. On rclone it is whatever the remote does with an upload over a name, and that
was checked on rclone's own local remote only, never on Drive. So both archives are in the
store, each proven, before that put, and a run that dies anywhere leaves them there. The
next run reads the journal first and decides by what the name is found holding: the new
archive, and the replace is finished; the old one, and it is forgotten and done again;
anything else, and the new archive goes over the name from `slim-tmp/` when that copy is
the one the journal recorded. **A snapshot retention removed is not put back** (r2.F4): a
run killed mid-replace leaves a lock the hourly job breaks half an hour on, and its prune
can then take the snapshot. So when the name holds nothing, retention's own rule
(`retained_deletions`) is asked of the set as the store lists it now with that snapshot
counted in. If it says the snapshot goes, the journal entry and both copies kept for the
replace are removed, the run says so, and nothing is written back. If it says the snapshot
stays, retention did not empty the name, dropping the copies would lose the snapshot, and
the proven new archive is put over the name as above. When the temporary copy is not the
journal's, the run stops, changes nothing,
removes nothing and names the copy that is good; `slim --restore <id>` puts the old
archive back over the name even then. A temporary object left behind is removed only when
no journal entry names it. All of it is judged on listings that answered and a journal
that read (r1.F4): a listing that fails, or a `slim.json` that does not parse, stops the
run with nothing changed.

**The way back: the old archive is kept** (r1.F7). Before anything is put over a
snapshot's name, the archive it holds is copied to `slim-old/<set>/<id>.tar.gz.gpg` and
proven there by md5: by the store itself where it can (rclone copies inside the remote),
else from the fetched file. It sits outside `sets/`, so retention, status's counts and the
nightly pull never see it, and a snapshot retention removes leaves its old archive behind
as an orphan.

```
keel backup slim --restore <id> --set keel    the old archive back over its name, proven; the rewrite forgotten
keel backup slim --purge --set keel           remove EVERY kept old archive of the set; only now is the space freed
keel backup slim --purge --id <id> --set keel one snapshot's kept old archive, by the same rules, and no other
```

`--restore` runs under the backup's lock, puts a `latest.json` that names the snapshot
back to what it said, drops the journal's entry so a later slim looks at the snapshot
afresh, and removes the kept copy last. **Only the archive the journal recorded goes back
over a name** (r2.F1): the journal must hold a rewrite of that snapshot (done, or
unfinished), and the object at `slim-old/<set>/<id>` must have the md5 the journal recorded
for the archive that rewrite replaced. Anything else stops with nothing changed and says
what it found, because the snapshot's own name may hold the only good copy. For the same
reason a kept copy that could not be proven is removed again while the name still holds the
archive that was fetched, and a snapshot whose `slim-old/` name already holds some other
object is left alone with the one safe way out named:

```
keel backup slim --purge --unproven <id> --set keel   remove one object under slim-old/ that no journal entry vouches for
```

It removes that one object only when the journal does not record it as the snapshot's old
archive and the snapshot's own name holds an object; the snapshot is not touched. `--purge` removes only an old archive whose
rewrite the journal marks done (while the store holds the slimmed snapshot the journal
recorded, or no snapshot of that id any more and retention's own rule says that snapshot
goes, which is how an orphan goes), or one that is a second copy of what its snapshot's
name still holds; an unfinished replace keeps its old archive. **An empty name is not
proof that retention emptied it** (r3.F2): for a rewrite that is done, restore and purge
ask `retained_deletions`, as recovery does, and all three ask it one way
(`slim_retention_list`), so they give the same answer for one snapshot: the rule is run
over the set as the store lists it, with the snapshot in question and every snapshot the
journal vouches a kept archive for (a done rewrite whose recorded old md5 is the object
under `slim-old/`) counted back in. A stray object under `slim-old/` is nobody's snapshot. A snapshot it would keep was lost some other
way and the kept archive is its only copy, so the restore puts it back and the purge
leaves it and says so; a snapshot it says goes is not restored, and the purge takes its
archive. Only the host that writes a set purges or restores it (r2.F3): the kept
archives are the only way back from its rewrites, and holding the store's login is not
being its writer. **Until the purge the store holds both, so a slim frees nothing by itself.**
`keel backup status` says how many are kept and their size, per set and in total
(`slim_old_mb`, apart from `store_mb`), and so does the dry run; the `backup-size` notice
counts them and says how much of the store they are (r2.F13). Purge after a `keel backup verify`, and after reading a restored snapshot if in doubt:
the mirror follows a rewrite on its next pull, so after a purge there is no other copy of
the old archive.

**No journal is not an empty journal** (r2.F11). A rewrite puts the set's first, empty
journal in the store and proves it there before it makes its first copy, and the journal
that names a replace is proven by the store's md5, like every other write, before the name
is written. So objects under `slim-tmp/<set>/` or `slim-old/<set>/` with no `slim.json`
mean the journal was lost: read as empty it would say no replace was under way, and the
proven new copy of one that was would be swept as a stray. A run that finds that, dry or
not, stops and removes nothing.

**The journal has a second copy** (r3.F1). `slim.json` is the only thing that says which
object under `slim-old/` is which snapshot's original, and it is put over its own name.
So before each put, the journal as it stood is put beside it as
`sets/<set>/slim.json.prev`, proven there, and copied to `work/<set>/slim.json.prev` on
this machine. When `slim.json` is absent or does not read, `slim --restore <id>`, and only
that, goes by the previous copy (the store's, else this machine's), says so, and holds the
kept archive to the same test: its md5 must be the one that copy recorded. This machine's
copy is only as new as its own last slim, and the restore ends by writing the journal it
went by back to the store. So when it goes by the local copy, every object under
`slim-old/<set>/` must have an entry in it, or the restore stops before changing anything
and names the ids it does not know: a copy older than the store's kept archives would
leave them unrecorded. It says at the start that it is going by the local copy, and says the copy was written
back only once that put has succeeded. With no journal
that reads, `--purge --unproven` removes nothing but an object that is byte for byte what
the snapshot's own name holds, and a run that finds copies and no journal names the
restore, not a removal.

**The journal is `sets/<set>/slim.json`, in the store**, so a resume skips what is done
from any machine. A snapshot is slim when the journal names the object the store holds now
(its md5), which also means a snapshot rewritten by anything else is looked at again, and
when it was slimmed under today's rules (r2.F6): each entry keeps the digest of what
decided its drops, so after a later scope fix the summary says how many were slimmed under
older rules and each is read again. One that the new rules leave alone takes today's
digest and keeps its entry. One they drop more from is rewritten again, once the archive
its first rewrite kept has been purged (`slim --purge --id <id>` lets that one go; the
set-wide purge removes every kept archive of the set, r3.F5): that archive is never
written over, and the run
says so and names the purge. Per
snapshot it holds the sizes before and after and what was lost by rule. The trees
themselves, path by path, are in `~/.keel-backup/logs/slim.jsonl`, one line a snapshot.

**Two locks, and the backup's own is held narrowly on purpose** (r1.F1, a decision). The
plan for this card said the slim takes the backup's lock so the hourly job and a slim never
run together. It does not hold it for the run: `.slim-lock` is held for the whole run, so
one slim runs at a time, and the backup's own lock only around step 3, waited for (30
minutes) rather than given up on. A whole run takes hours, and holding the backup's lock
across it would skip every hourly snapshot until the staleness alarm fired. So the hourly
job does run while a snapshot is being read and proven, and what it does then is not
undone: a snapshot it pruned is found gone under the lock and never put back, and a
snapshot it has a publish pending for (`work/<set>/pending/`) is skipped for the run and
asked about again under the lock, so a pending blob is never put back over a rewrite. An
hourly job that starts during step 3 skips that one hour. Step 3 is seconds: each write is
proven by asking the store for that one key's md5 (`store_md5`, r2.F15), which on a folder
store hashes the one object written and on Drive reads its row. No answer is kept across
two writes, and the set's whole listing, which status reads, is refreshed once, when the
run ends. The dry run takes only the first lock and writes nothing to the store.

**What the dry run reads, and the one thing it writes.** The set's listing, its
`slim.json`, the listing of `slim-old/<set>/`, and every snapshot not yet slim (or
`--limit` of them), each downloaded, decrypted and unpacked under `$TMPDIR` and removed
before the next. It writes nothing to the store. Locally it writes `slim-approved.json` and the cached
listing status reads. It reports, per snapshot and in total, the files and unpacked
bytes each rule drops, the size in the store before and (packed, so nearly exact) after,
and a rough time for the rewrite. A full dry run downloads the whole pending set, so
`--limit` first.

**The slim's two locks are the tool's one lock** (see "The lock", c-750), at two names:
`.lock` and `.slim-lock`, each a link whose target is the holder's pid, taken with
`lock_take` and released with `lock_release`. The slim makes, reads and breaks no lock by a
rule of its own, so a stale one is judged and broken exactly as the hourly job's is (the
rename that r1.F16 asked for is `lock_take`'s), and a slim killed less than half an hour
ago leaves a lock the next slim will not break yet: it says so and stops. `lock_take` ends
a run that cannot have the lock, so the slim calls it in a subshell and reads the lock to
see whether it now names this run; around a replace it waits by taking again. **A killed
run's unpacked snapshot is removed by the next run** (r1.F8): a kill skips the exit trap
and leaves a whole decrypted snapshot under `$TMPDIR`, so a run that holds `.slim-lock`
appends one line to `.slim-lock.work` beside it (its pid, the temp root it ran under, its
temporary directory) and takes the line out at release. The next run to hold the lock reads
the lines dead runs left and removes each directory, only when it is named as the tool
names its own, sits directly under the temp root its own record names (launchd and a
terminal do not share one, so the next run's root is not the test), and is a real
directory, not a link. **A record goes only when its directory is gone** (r2.F5): one that
is not removed (its pid is running, the name or the place is wrong, it is a link) keeps its
line and the run says why, so the place a decrypted snapshot may lie is never forgotten.
A run writes its own line before it sweeps (r3.F6), since a sweep removes whole trees and
can be slow. The exit trap treats a run as a slim when the verb was `slim` and `.slim-lock`
names its pid: a dead slim's stale lock names a pid the system hands out again, and an
hourly run given that pid must not release a lock that was never its own. The record is
not asked, so a slim that ends before its line is written still releases its lock; the
record decides only whether a line is taken out.

**The tests reuse a run they have already made.** Each slim test is a handful of runs of
the real tool, a second or two apiece, and most of those are a prelude many tests share.
So the fixture (`tests/backupslimcase.py`) keeps what the tool left the first time it was
given a set of inputs (the tool's own text, what was asked, the environment the test
added, and every entry's path, kind, permission bits and bytes under the store, the backup
home, the live tree and the temp root; not modification times, which no copy shares and
the slim reads only for a lock) and hands a copy to a later run whose inputs are the same; any run with an input of its own is made for real. The fixture
snapshots' archives and the board are likewise made once a process.
`SLIM_TESTS_EVERY_RUN=1` makes every run for real. The five modules take about 280
seconds between them this way, down from about 490 (measured 2026-10-11).

**The tests' seam.** The slim's tests stop a run dead at a named step
(`KEEL_BACKUP_SLIM_DIE_AT`) or holds it there until a file appears
(`KEEL_BACKUP_SLIM_HOLD_AT`), to assert what an interruption leaves in the store. The tool
honours either only when the store is a folder and `KEEL_BACKUP_SLIM_TEST=1` is set as
well, so a variable left in a shell does nothing to a run against Drive (r1.F12). The size
warning's threshold has a plain override, `KEEL_BACKUP_SIZE_WARN_MB`: not a gated seam,
every run reads it, and a value that is not all digits is ignored for the built-in 8192
(r3.F8). The
sums are always the tool's own modules: `python -m` looks in the current directory first,
so the tool calls them with `-P`, and a slim run from another checkout's root does not
borrow that checkout's `keel/`.

**Disk.** One snapshot is on disk at a time. Before each fetch the free space under
`$TMPDIR` must be 12 times the snapshot's size in the store plus 1 GB
(`KEEL_BACKUP_SLIM_DISK_FACTOR`, `KEEL_BACKUP_SLIM_DISK_FLOOR_MB`), or the run stops there
and says so. Everything is streamed: `gpg` into `tar`, `tar` into `gzip`.

**After a rewrite.** Status and retention count what they counted, since no id changed;
the sizes are the listing's, refreshed when the run ends. The mirror fetches a rewritten
snapshot again on its next pull if it holds it (its md5 changed). The space is freed
only at `--purge`, and on Drive later still: a removed object sits in the trash for 30
days, and the content a name held before stays as an old revision for about as long.

**A read that lands on a replace fetches once more** (r1.F13). The weekly verify and the
nightly pull take no backup lock, so either can list a snapshot and fetch it a moment
after a slim has put the new archive over its name: whole bytes, and an md5 the old
listing does not have. That is a changed object, not an unreadable set, and it must not
raise the card that says so. Both list once more and fetch again against the fresh md5
(`fetch_blob`, `pull_again`); a mismatch against the fresh listing fails as before.

## Turned on from the first run: a folder as the store (c-678)

Everything above took a terminal to set up. The first run's Back up step
([onboarding](89-onboarding.md), "Back up") turns on the folder form with one tap:
`firstrun.backup.on` {`folder`}, `keel/backupsetup.py`. In order, each step refusing before
the next:

1. **The folder.** A whole path, made if it is not there and written to once. One inside
   the install is refused: "That folder is inside the install, so the backup would copy
   itself.", and the refusal carries the suggested folder (`~/shipyard-backup`, c-729). One that has
   files in it is refused while this computer holds no backup key ("That folder is not
   empty, and this computer has no backup key for what is in it. Pick an empty folder."):
   what is in it cannot be this computer's store, and a turn-on that failed could not be
   taken back out of it. A folder that cannot be listed counts as not empty. With a key, a
   folder that holds that key's store is taken.
2. **Nothing is replaced.** A config that already names a store is refused, and so is a
   computer that already has another backup's job, asked for BOTH labels, the hourly
   snapshot's and the weekly proof's, before anything is written
   (`backupsetup.jobs_before`, c-678 review r2.F5). The jobs' labels are one per user
   account; loading one copies this install's file over the installed one and stops what
   ran under the label, and unloading removes the installed file, so another install's job
   would be replaced on success and removed on failure. Refused: a label whose job is
   loaded, and a label with an installed file whose bytes are not this install's own
   rendering of that job (a job that is installed and booted out is not listed as loaded,
   so the file is read). The rendering carries the install's config path, which is what
   tells two installs apart; the code checkout and the tool's path can be shared and are
   never compared.
3. **The config.** `[backup] store = "file:<folder>"`, `sets = ["keel"]` and `since`, when
   this turn-on happened (the board's clock, in UTC, `backupsetup.named`), in one
   checked and backed-up edit (`setupconfig.edit`). `since` is how the step and the drain
   tell this install's copies from an earlier install's ("Whose they are", below); a
   failed turn-on puts the whole text back, the key with it. It is a config verb
   (`onboarding.CONFIG_VERBS`), so the deck reads the store on its next start.
4. **The keys.** The tool's own `init`, run with that config: it proves the store and
   makes the passphrase where this computer has none.
5. **The jobs.** The hourly snapshot and the weekly restore proof, written under the
   install's `services/` (as the app's own services are, never into the code's `etc/`) and
   loaded.
6. **The first copy** (c-757, `backupsetup.first_copy`). One snapshot, started now by this
   call with `backup.start`, the detached start the drain uses for the nightly pull and for
   an overdue snapshot, and never waited for: the answer says `started`, and what became of
   the run is the step's to read. It was left to the service manager, which runs the
   hourly job as it is loaded on launchd and may not elsewhere, and the page said "writing
   it now" either way. A run the manager started in the same second and this one cannot
   both write: the tool's own lock decides, and the one that finds it held says so and
   exits 0. A start that cannot be made does not undo the turn-on: the backup is on, the
   step says no copy is being written, and the drain starts the next one. It is the last
   thing the call does: the answer, with the passphrase shown once, is built first, and
   whatever the start raises is `started: false` (review r1.F11).

**gpg is asked for before anything is written** (c-757). Every snapshot is encrypted with
gpg; `init` needs only openssl. So on 2026-10-12 a Mac with no gpg was turned on, got its
key and its jobs, and never wrote a copy. The turn-on now asks the machine check
(`prereqs.gpg_check`, afresh) first and refuses: "Backup needs gpg, and this computer has
none where the backup looks. The Check this computer step has its row, with how to install
it." The check looks where the jobs look (`backup.PATH_ENTRIES`, the PATH the service
manager hands them). The tool asks too, at the start of every snapshot (`gpg --version`),
and dies saying gpg did not run and how to install it, where it used to build the archive
and then say only "gpg refused to encrypt".

**Every way a snapshot dies leaves its reason** (c-757, `on_exit` in `bin/keel-backup`).
`last_error` was written on one path, a publish that failed. Now the exit trap writes it
for any failed `snapshot`: what `die` last said (its first line), or "the run stopped with
exit N" for an abort with no words, with `last_error_at`. A signal writes nothing (a job
being stopped is not a failure), and the next success empties `last_error`. The failed-run
card's brief carries the same sentence ("It said: ...").

When it is armed (review r1.F8): `cmd_snapshot` sets `RECORD_ON_FAIL` itself, after its
arguments are checked and before it reads the config and takes the lock. So a mistyped
flag by hand, which failed no backup, records nothing, while a run that cannot make its
lock or read its settings records why. It is unset once `last_success` is written and its
notice retired, so nothing that goes wrong in the closing sums or the status writes "the
run stopped" over a copy that was made. A run that finds the lock held exits 0 and records
nothing. A narrowed run (`--set`) that fails still records and one that succeeds clears
nothing, which is the tool's own rule for a narrowed run.

**The weekly proof leaves its reason the same way** (review r1.F2): `cmd_verify` sets
`RECORD_VERIFY_ON_FAIL` after its arguments are checked, and the trap writes
`last_verify_error` and `last_verify_error_at`. Only two of its deaths stamped one (a set
that does not read back, a store that is shared), so a proof that died anywhere else was
later shown as one that did not run. Those two keep their own words and disarm the trap.
A proof that passed disarms it too, as soon as `last_verify` is on file, and so does each
way out that found nothing to prove (fix check D2): left armed, a non-zero exit after the
stamp (the closing lines, or `migrate`, which carries on after its own proof) wrote "the
proof stopped" over a proof that passed.

**`state_set` takes a lock** (review r1.F8): the state file is read, changed and written
back by runs that hold different locks or none (a snapshot, a pull, the weekly proof, a
death before the lock), so two at once lost one writer's key. The whole read-change-write
holds an `flock` on `state.json.lock`, beside the state file (not on the state file, which
is replaced by rename). A filesystem that refuses `flock` (some network homes) gets the
record without the lock, as every record was written before: the lock guards two writers
at once, and a record that dies for want of it loses every run's (fix check D4).

**All or nothing** (c-678 review, `backupsetup.undo`). A failure in step 4 or 5 puts back
everything that call made, then refuses ("The backup could not be set up, so nothing was
turned on: ...", "The backup's hourly job could not be started, so nothing was turned on:
..."): the config's text; each job, put back to how it was before the call (none was
loaded before, since a loaded one is refused, so every job it tried ends not loaded: one
whose file this call installed is unloaded, `Manager.unload`, which removes the file, and
one whose file was installed before is unloaded with its file kept,
`Manager.unload(job, keep=True)`: a bootout on launchd, disable and stop on systemd, so it
ends installed and not loaded on both (`Manager.stop` would leave a systemd job enabled,
which reads as loaded); so a retry is never refused as another install's backup; the files it wrote under `services/`
always); whatever it put into a
folder that was empty before (never the Finder's `.DS_Store`, which was there);
and the key, when THAT call made it, with the notice card the tool staged its passphrase
on DURING this call moved to done (the cards open before the call are recorded first and
left open: they are another key's, or the user's unread one). A key that was there before
is never touched. Each part is taken back under its own guard, so one file that cannot be
removed does not keep the key in place, and the answer is still the refusal, not the
error of taking it back. So there is no state in
which a key exists and its passphrase was never shown, and the next tap starts clean. The
config is as it was, so the deck needs no restart after a refusal.

**The passphrase is shown once.** The verb's answer carries it only when that call made
it; the page shows it with Copy and one tick, "I saved it somewhere that is not this
computer.", and ticking it drops it from the page. It is held in the page's memory only,
never in the browser's storage. A key this computer already had is not read back to a page:
the answer says it was kept, and where the key file is. The tool still files its own
notice card with the passphrase, as it does for an install set up by hand.

`backupstatus.status(cfg, now)` is what the step's rows read, each time, from what is
there (`keel/backupstatus.py`, c-757; `backupsetup.status` is the same function under its
old name). Nothing is assumed and nothing is stored. Two readings are kept for five
minutes (`readiness.KEEP_SECONDS`), like readiness's other slow ones (`readiness.kept`):
the gpg check, and the store folder's listing, since the page asks for the state every
four seconds while a copy is pending and the folder may be on another disk (review
r1.F12). A listing that found no copy is not served once the copy row says a copy was
written: the folder is read again on that look (`kept_first`, fix check D1), or the proof
row said "once there is a copy to prove" beside "First copy written" for five minutes.
That second answer is kept in its turn, "no copy" included (second fix check, D6), so a
success on file with nothing in the folder (a set that had not changed stamps a success
and writes nothing; a folder that went away) costs two listings in five minutes and not
one on every look.

- **The copy** (`copy`): `written` when `state.json` holds a `last_success` and no run has
  failed since; `writing` while a live process holds the tool's lock (`backup.lock_live`),
  and only then (review r1.F1: it was also said for the first minute after the turn-on,
  with no run at all); `failed` with `last_error` as the tool left it, and `at` when a
  copy was written before it; `none` when there is no copy, no run and no error, `late`
  once that has lasted ten minutes (`LATE_SECONDS`). A failure's `fix` says what the drain
  will do, in its own numbers (review r1.F6): with no copy yet, another run within a
  minute or two, then about every ten minutes, up to three an hour; after a copy, the next
  hourly run.
- **The proof** (`proof`): `proved` with `last_verify`; `failed` with `last_verify_error`;
  `missed` when the weekly time is over twelve hours past (`MISSED_SECONDS`) with neither
  since, AND a copy of this install's was in the store's folder before that time
  (`first_kept`, the oldest snapshot there by its own name, not older than the turn-on):
  a proof is owed only for a copy that was there to prove, so a backup turned on after
  the weekly time, or one whose first copy came after it, has missed nothing; a store that
  is not a folder is never said to have missed; else `waiting`. Each carries `next`, the
  next time the weekly job is due, worked out from `backup.VERIFY_WHEN` in the zone of
  `now`, and its sentence names that day.
- **Whose they are** (`ours`). The backup's home is one per user account, so a second
  install on the account reads the first one's `state.json`: it showed "First copy
  written" and a proven restore for a folder with nothing in it. A stamp counts only when
  it is not older than `since`, when this install's backup was turned on: the config's
  `[backup] since`, which the turn-on writes in the same edit as the store (review r1.F5).
  It was the hourly job file's time, and `keel backup install` writes that file again,
  after which the install's own copies read as an earlier install's and the page said "No
  copy has been written since backup was turned on N minutes ago". An error with no stamp
  of its own, written by the tool before c-757, cannot be placed and is not shown where
  `since` is known.
- **The key alone disowns a reading** (fix check D3, second fix check D7), on the page
  and in the drain (`backupstatus.turned_on`; the drain through `backupstatus.own_stamp`,
  "When the hourly job stops", above). An install with no `since` (one turned on before
  the key existed, a store set up by hand) takes every stamp as its own, exactly as
  before the key existed: the page shows the copy on file, and the drain reads
  `last_success` raw. So does one whose `since` is not a time, or is later than now (a
  hand edit, a clock that was ahead at the turn-on): believed, that would disown every
  success this install ever writes, and the drain would start three runs an hour for
  good. Nothing reads the job file's time. For one round of review the page fell back to
  it while the drain did not, and the page promised a copy "within a few minutes" that
  the drain, holding a fresh success, would not start. Every turn-on writes the key, so
  an install turned on from this card on is always covered.
- `gpg` (the machine check), `same_disk` (the folder shares a device with the install,
  which says nothing about whether it is synced elsewhere), `writable`, `key`, `since` and
  `log`.

`backupstatus.verdict` is the step's own state from that, one rule (review r1.F3, r1.F4):
done means backup is on and a copy of this install's has been written, and it never goes
back. Off: not done. On with no copy yet: done and not confirmed (`sure: False`, `word`
"copy pending") while one is being written or is still to come, and NOT done once the
first run failed or never started. On with a copy: done, and not confirmed with its own
word and a `why` that names it when the folder cannot be written ("folder missing"), else
when a run failed after the copy ("last run failed"), else when the proof failed ("proof
failed"). A missed proof stays on its row. The readiness row `backup` says only "backup is
on, into <store>" (review r1.F10): it claims nothing about copies.

Not in this verb: an rclone store, the nightly pull, restoring from the page.

## How to change it

Change the scope in exactly one place: the set's own `*_roots` and `*_find` functions in
`bin/keel-backup`. A backup whose scope is described in two places eventually backs up
something different from what it checks.

Then run `bin/keel-backup-selftest`, on macOS and on Linux (it installs nothing). It exercises retention against fabricated
ids spanning a year, publishing through a store that refuses a put, the one-writer refusal
and `--take-over`, the pull that never deletes, the alarms raised and retired, the privacy
check, and the move off GitHub, all against a `file:` store; where rclone is installed a
second pass runs the core of it through rclone's own local backend, including a stub
rclone answering `invalid_grant`. It touches nothing real and needs no network. It is not
in `make test` because it needs `gpg` and about a minute.

Adding a root changes the manifest, so the next snapshot legitimately re-encrypts and
re-uploads that set once. That is the skip-unchanged rule working, not failing.
