"""What the Back up step shows (c-757): what is observed, each time, and nothing assumed.

On 2026-10-12 the first teammate turned backup on and the step said "Done" above a spinner
that read "The hourly job is writing it now." and a grey "First proof on Sunday". No copy
was ever written (his Mac had no gpg), and nothing on the page could have said so: the step
was done as soon as the config named a store, the spinner was drawn whenever no success was
on file, and the proof row was a fixed sentence. This module is the reading that replaced
those three: `status(cfg, now)` for the step's rows, `verdict(found)` for the step itself.

Everything is read from what is there: the tool's `state.json` and its lock in the backup's
own home, the store's folder, and the install's config. Two readings are kept for five
minutes (`readiness.KEEP_SECONDS`) like the other slow ones (`readiness.kept`): the gpg
check, which runs a program, and the store folder's listing (`first_kept`), which may be
on another disk or a synced folder. A listing that found no copy is not served once the
copy row says one was written (`kept_first`, fc.D1): the folder is read again, so the
proof row never waits for "a copy to prove" beside a copy. Read again once, and that
answer is kept in its turn (fc2.D6): a success on file with no copy in the folder (a set
that had not changed, a folder that went away) is not a listing on every look. Nothing
else is kept, and nothing is stored.

**The copy** (`copy_of`), one of:

- `written`: the tool recorded a success (`last_success`), and no run has failed since;
- `writing`: a run holds the tool's lock (`backup.lock_live`), and only then (r1.F1): a
  start that could not be made, or one that has not reached its lock yet, is not a copy
  being written;
- `failed`: the last run died, with the reason the tool left (`last_error`: every way a
  snapshot can die writes one, `on_exit` in `bin/keel-backup`). It carries `at` when a
  copy was written before it;
- `none`: no copy, no run and no error. Under `LATE_SECONDS` after the turn-on that is a
  copy still to come (the drain starts one itself, `keel/backupdue.py`); after it, it is a
  first copy that never started, and the step says so.

**The proof** (`proof_of`): `proved` with when, `failed` with the tool's reason
(`last_verify_error`), `missed` when the weekly time passed over `MISSED_SECONDS` ago with
neither, else `waiting`. A proof was only ever owed for a copy that was there to prove:
`missed` is said only when the store's folder holds a copy of this install's written
before that weekly time (`first_kept`, read from the snapshots' own names). A backup turned
on after it, or one whose first copy came after it, has missed nothing and waits for the
next. A store that is not a folder cannot be read here, so it is never said to have
missed. Each carries `next`, the real next time the weekly job is due (`next_proof`, from
`backup.VERIFY_WHEN`), and its sentence names that day.

**Readings belong to this install** (`ours`). The backup's home is one per user account, so
a second install on the account finds the first one's `state.json`. A stamp counts only
when it is not older than `since`, when this install's backup was turned on. That time is
the config's `[backup] since`, which the turn-on writes in the same edit as the store
(`backupsetup.named`, r1.F5): it was the hourly job file's time, and `keel backup install`
writes that file again, after which the install's own copies read as an earlier install's.
An error with no stamp of its own (written by the tool before c-757) cannot be placed, so
it is not shown where `since` is known.

The key is the only thing that disowns a reading (fc.D3, fc2.D7). An install with no
`since` (one turned on before the key existed, a store set up by hand), or with one that
is not a time, or with one later than now (a hand edit, a clock that was ahead: believed,
it would disown every success this install ever writes), takes every stamp as its own,
exactly as before the key existed. The job file's time is read by nothing. The drain's
due test (`own_stamp`, `keel/backupdue.py`) asks the same question of the same key, so
the page never promises a copy the drain will not start. Every turn-on writes the key,
so an install turned on from here on is always covered.

**The step** (`verdict`, r1.F3 and r1.F4, one rule): done means backup is on and a copy of
this install's has been written, and it never goes back to not done. What is wrong after
that makes it done and not confirmed (`sure: False`) with a word of its own, so the step
is never "Done" over a row that says otherwise.

Times: the tool stamps in UTC (`2026-10-09T19:35:45Z`); `now` is an aware datetime, and
the proof's day is said in `now`'s own zone, which is the zone the weekly job runs in.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from keel import backup, prereqs, readiness
from keel.setupconfig import SetupError, install_of

FILE = "file:"
KEY = "backup.key"
STATE = "state.json"
SERVICES = "services"
LOCK = ".lock"
LATE_SECONDS = 10 * 60          # no copy, no run, no error for this long: it never started
MISSED_SECONDS = 12 * 3600      # past the weekly time with no proof and no error: missed
CHECK_STEP = "Check this computer"
NO_GPG = ("Backup needs gpg, and this computer has none where the backup looks. "
          f"The {CHECK_STEP} step has its row, with how to install it.")


def suggested() -> str:
    return str(Path.home() / "shipyard-backup")    # c-729: named for the product, as the units are


def store_folder(cfg) -> str | None:
    store = cfg.backup_store or ""
    return store[len(FILE):] if store.startswith(FILE) else None


def gpg(fresh: bool = False) -> dict:
    """The gpg check of Check this computer (`prereqs.gpg_check`), kept like the other slow
    readings; `fresh` for the turn-on, which never decides on a kept one."""
    return readiness.kept(("gpg",), prereqs.gpg_check, fresh)


def when(stamp) -> datetime | None:
    """One of the tool's stamps, or an ISO time, as an aware datetime; None for neither."""
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        found = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def turned_on(cfg, now: datetime | None = None) -> datetime | None:
    """The config's `[backup] since` as a time. None where there is none, where it is not a
    time, and where it is later than `now` (fc.D3, the module's note)."""
    at = when(getattr(cfg, "backup_since", None))
    now = now or datetime.now(timezone.utc)
    return at if at is not None and at <= now else None


def since(cfg, now: datetime | None = None) -> str | None:
    """When this install's backup was turned on, as the page carries it: `turned_on` in
    UTC, None where the config has no usable `since` (the module's note)."""
    at = turned_on(cfg, now)
    return at.astimezone(timezone.utc).isoformat(timespec="seconds") if at is not None else None


def ours(stamp, began: datetime | None) -> datetime | None:
    """`stamp` as a time when it is this install's: not older than its turn-on (`began`).
    With no turn-on on file every stamp is its own. A whole second is allowed, since the
    tool's stamps and the turn-on's time are both cut to the second."""
    at = when(stamp)
    if at is None or began is None:
        return at
    return at if at >= began - timedelta(seconds=1) else None


def own_stamp(cfg, stamp: str | None, now: datetime | None = None) -> str | None:
    """One of the tool's stamps, as it wrote it, when it is this install's, else None: the
    drain's reading of `last_success` (`keel/backupdue.py`). By the config's `since`, as
    the page reads it (`turned_on`): with none the stamp is returned as it is."""
    began = turned_on(cfg, now)
    if began is None:
        return stamp
    return stamp if ours(stamp, began) is not None else None


def same_disk(cfg, folder: str | None) -> bool | None:
    """Whether `folder` (or the nearest folder above it that exists) is on the disk the
    install is on; None where that cannot be read. It says a device is shared and no more:
    a folder that is synced somewhere else shares the home's device too."""
    if not folder:
        return None
    try:
        there = Path(folder)
        while not there.exists() and there != there.parent:
            there = there.parent
        return os.stat(there).st_dev == os.stat(install_of(cfg)).st_dev
    except (OSError, SetupError):
        return None


# ----- the copy -----

# What happens next, true to the drain (`keel/backupdue.py`, r1.F6). With no success of
# this install's on file a run is owed at once: started after two passes awake, tried again
# RETRY_SECONDS after one that ended with none, STARTS_AN_HOUR at most. With a success under
# an hour and a quarter old the drain starts nothing, and the hourly job is what runs next.
FIRST_AGAIN = ("Shipyard starts another within a minute or two while this computer is awake, then again about "
               "every ten minutes, up to three an hour.")
HOURLY_AGAIN = "The next hourly run tries again."
SOON = ("No copy is being written right now. Shipyard starts one by itself within a few minutes. "
        "You can go on to the next step.")


def copy_of(paths: backup.Paths, state: dict, began: datetime | None, now: datetime, log: str) -> dict:
    """The first copy as it stands: `{state, at, said, fix}` (the module's note)."""
    written = ours(state.get("last_success"), began)
    error = state.get("last_error") or ""
    failed = ours(state.get("last_error_at"), began) if error else None
    at = written.isoformat(timespec="seconds") if written else None
    if error and (failed is not None or began is None):
        return {"state": "failed", "at": at, "said": error,
                "fix": f"{HOURLY_AGAIN if written else FIRST_AGAIN} The run's log is {log}."}
    if written:
        return {"state": "written", "at": at, "said": "", "fix": ""}
    if backup.lock_live(paths, LOCK):
        return {"state": "writing", "at": None, "fix": "",
                "said": "The first copy is being written now, in the background. You can go on to the next step."}
    waited = (now - began).total_seconds() if began else None
    late = waited is None or waited >= LATE_SECONDS
    return {"state": "none", "at": None, "late": late,
            "said": (f"No copy has been written since backup was turned on {int(waited // 60)} minutes ago, "
                     "and none is being written now." if late and waited is not None
                     else "No copy has been written, and none is being written now." if late else SOON),
            "fix": f"Shipyard starts one by itself while this computer is awake, and files a notice on the board "
                   f"if none succeeds. The run's log is {log}."}


# ----- the proof -----

def weekly(now: datetime) -> datetime:
    """The weekly proof's time in the week of `now`, in `now`'s own zone. launchd counts
    Sunday as 0 and Python Monday as 0 (`backup.VERIFY_WHEN`)."""
    day = (backup.VERIFY_WHEN["Weekday"] - 1) % 7
    start = now.replace(hour=backup.VERIFY_WHEN["Hour"], minute=backup.VERIFY_WHEN["Minute"], second=0, microsecond=0)
    return start + timedelta(days=day - now.weekday())


def next_proof(now: datetime) -> datetime:
    """The next time the weekly proof is due, strictly after `now`."""
    due = weekly(now)
    return due if due > now else due + timedelta(days=7)


def day_of(at: datetime) -> str:
    return f"{at:%A} {at.day} {at:%B}"


SNAPSHOT = "%Y%m%dT%H%M%SZ"     # how the tool names a snapshot: the time it was taken
BLOB = ".tar.gz.gpg"


def first_kept(folder: str | None, began: datetime | None) -> datetime | None:
    """When the oldest copy of this install's still in the store's folder was written
    (`sets/<set>/snapshots/<year>/<month>/<id>.tar.gz.gpg`), by its name. One older than the
    turn-on is an earlier install's, there before this backup was on, and is not counted.
    None with no such copy, or for a store that is not a folder."""
    found = []
    try:
        names = [path.name for path in Path(folder).glob(f"sets/*/snapshots/*/*/*{BLOB}")] if folder else []
    except OSError:
        return None
    for name in names:
        try:
            at = datetime.strptime(name[:-len(BLOB)], SNAPSHOT).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if began is None or at >= began - timedelta(seconds=1):
            found.append(at)
    return min(found) if found else None


def kept_first(folder: str | None, began: datetime | None, copied: bool = False) -> datetime | None:
    """`first_kept`, kept like the other slow readings (r1.F12), for `readiness.KEEP_SECONDS`:
    the page asks for the state every few seconds while a copy is pending, and the folder
    may be on a slow disk. `copied`: the copy row says a copy was written, so a "no copy"
    kept from before it is stale and the folder is read again (fc.D1). That second answer
    is kept under a key of its own, "no copy" included (fc2.D6), so the folder is listed
    at most twice in one keep, and never twice on one look."""
    key = ("backup-kept", folder, began.isoformat() if began else None)
    listed = []

    def read():
        if not listed:
            listed.append(first_kept(folder, began))
        return listed[0]

    found = readiness.kept(key, read)
    if found is None and copied:
        found = readiness.kept((*key, "copied"), read)
    return found


def proof_of(state: dict, began: datetime | None, now: datetime, kept: datetime | None, log: str) -> dict:
    """The restore proof as it stands: `{state, at, said, fix, next}`. `kept`: when the
    oldest copy in the store was written (`first_kept`), None with none to prove."""
    coming = next_proof(now)
    due = coming - timedelta(days=7)
    out = {"next": coming.isoformat(timespec="seconds"), "at": None, "fix": ""}
    proved = ours(state.get("last_verify"), began)
    error = state.get("last_verify_error") or ""
    failed = ours(state.get("last_verify_error_at"), began) if error else None
    if error and (failed is not None or began is None):
        return dict(out, state="failed", said=f"The last restore proof failed: {error}",
                    fix=f"It runs again by itself on {day_of(coming)}. Its log is {log}.")
    if proved:
        out["at"] = proved.isoformat(timespec="seconds")
    # owed only for a copy that was there to prove when the weekly time came
    owed = kept is not None and kept < due and (now - due).total_seconds() > MISSED_SECONDS
    if owed and (proved is None or proved < due):
        return dict(out, state="missed", said=f"The restore proof due {day_of(due)} did not run.",
                    fix=f"It runs again by itself on {day_of(coming)}. Its log is {log}.")
    if proved:
        return dict(out, state="proved", said=f"The next one is due {day_of(coming)}.")
    # with a copy there, the day alone; with none, the day and what it waits for
    tail = "." if kept is not None else ", once there is a copy to prove."
    return dict(out, state="waiting", said=f"First proof on {day_of(coming)}{tail}")


# ----- the step -----

def status(cfg, now: datetime | None = None) -> dict:
    """What the Back up step shows: off with the suggested folder, or on with its rows."""
    now = now or datetime.now()
    now = now if now.tzinfo else now.astimezone()
    if not cfg.backup_store:
        return {"on": False, "suggested": suggested(), "gpg": gpg(), "same_disk": same_disk(cfg, suggested())}
    paths = backup.paths_from(cfg)
    folder = store_folder(cfg)
    try:
        state = json.loads((paths.backup_home / STATE).read_text())
    except (OSError, ValueError):
        state = {}
    state = state if isinstance(state, dict) else {}
    said_on = since(cfg, now)
    began = when(said_on)
    log = str(paths.logs / f"{backup.LOG[backup.LABEL]}.out")
    copy = copy_of(paths, state, began, now, log)
    kept = kept_first(folder, began, copied=copy["at"] is not None)
    proof = proof_of(state, began, now, kept, str(paths.logs / f"{backup.LOG[backup.VERIFY_LABEL]}.out"))
    return {"on": True, "store": cfg.backup_store, "folder": folder,
            "writable": os.access(folder, os.W_OK | os.X_OK) and Path(folder).is_dir() if folder else None,
            "same_disk": same_disk(cfg, folder), "gpg": gpg(),
            "copy": copy, "first": copy["at"], "proof": proof,
            "key": str(paths.backup_home / KEY), "since": said_on, "log": log}


PENDING = "copy pending"
NO_FOLDER, RUN_FAILED, PROOF_FAILED = "folder missing", "last run failed", "proof failed"


def first_sentence(said: str) -> str:
    return said.split(". ")[0].rstrip(".")


def verdict(found: dict) -> tuple[bool, str, dict]:
    """`(done, why, extra)` of the Back up step from its status (the module's note).

    1. Off: not done.
    2. On, no copy of this install's yet: done for Next and not confirmed (`sure: False`,
       `word` "copy pending") while one is being written or is still to come; NOT done once
       the first run failed or never started.
    3. On, with a copy: done, always. Not confirmed, with its own word and a `why` that
       names it, when the folder cannot be written ("folder missing"), else when a run
       failed after the copy ("last run failed"), else when the proof failed ("proof
       failed"). A missed proof stays on its row."""
    carried = {"backup": found}
    if not found["on"]:
        return False, "no backup is set up: the board lives only in this install", carried
    where = found["folder"] or found["store"]
    copy = found["copy"]
    if copy["at"] is None:
        if copy["state"] == "failed":
            return False, f"backup is on, but the last run wrote no copy: {first_sentence(copy['said'])}", carried
        if copy["state"] == "none" and copy.get("late"):
            return False, "backup is on, but no copy has been written and none is being written", carried
        coming = ("The first copy is being written in the background" if copy["state"] == "writing"
                  else "The first copy has not started yet: Shipyard starts it by itself, in the background")
        return True, f"backup is on, into {where}. {coming}", {**carried, "sure": False, "word": PENDING}
    if found["writable"] is False:
        return True, (f"backup is on, but {where} is not there or cannot be written, so no copy is being made"), {
            **carried, "sure": False, "word": NO_FOLDER}
    if copy["state"] == "failed":
        return True, f"backup is on and has a copy, but the last run stopped: {first_sentence(copy['said'])}", {
            **carried, "sure": False, "word": RUN_FAILED}
    if found["proof"]["state"] == "failed":
        return True, "backup is on and has a copy, but the last restore proof failed", {
            **carried, "sure": False, "word": PROOF_FAILED}
    return True, f"backup is on, and the first copy is written, into {where}", carried
