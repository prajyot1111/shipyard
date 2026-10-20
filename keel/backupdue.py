"""The hourly snapshot, watched from the drain: started when it is overdue, and said on the
board when none succeeds (c-750).

The hourly job is the service manager's to start (`keel/backup.py`), and on 2026-10-11 the
owner's Mac had not started it for 33 hours while awake for 24 of them. Nothing had failed,
so nothing was said: the job's last exit was 0, the state file's `last_error` was empty,
and the tool's staleness notice is raised by `status --announce`, which runs inside the job
that was not running. A check that lives in the thing it checks cannot see it stop.

The drain passes only while the machine is awake and is watched itself (the deck's health
reads its last pass), so it is the one place that can see the job stop. Each pass `upkeep`
reads the tool's `last_success` and does three things:

- **Counts.** Once a run is owed (the last success is over an hour old) it adds up the time
  the drain was passing, in `snapshot-watch.json` beside the tool's state file. A gap
  between passes of more than AWAKE_GAP_SECONDS (or a poll and a half of the drain's
  `poll_seconds` plus a minute, where that is longer: `awake_gap`) is a machine asleep (or a drain stopped) and counts for nothing, so a laptop closed overnight has not been overdue all night.
  Keel has no other reading of when the machine woke; the drain's own passes are one it
  already has. A long DarkWake in which the drain passes counts, and it can start a run
  there, so the time was owed.
- **Starts.** When the last success is older than the interval plus MARGIN_SECONDS and no
  run holds the tool's lock, it starts `bin/keel-backup snapshot`, detached. The tool's
  own lock is what keeps two runs apart: a run that finds it held says so and exits 0.
  Never on one pass alone: AWAKE_PASSES in a row, each inside the gap of the one before,
  so a single pass in a DarkWake, or the first after the lid opens with the network still
  down, starts nothing. A run the drain started that ended with no success is tried again
  RETRY_SECONDS later (a failure for lack of network takes seconds, and an hour's wait
  for it was the tool's failure card standing for an hour), and never more than
  STARTS_AN_HOUR in one interval.
- **Says.** When the count reaches OVERDUE_SECONDS less the first hour (so three hours
  after the last success on a machine awake throughout), it files one notice under the
  tool's own `backup-stale` key, unless one is open already, once per missing success, and
  not while a run holds the lock. The run is started first: a board that will not take
  the card costs the card, never the run. The next run that succeeds retires it, as it
  retires its own (`clear_broken`).

**Whose success** (c-757 r1.F6). The backup's home is one per user account, so a second
install on the account finds the first one's `last_success`. Read raw, a recent success of
the EARLIER install held this install's drain at "not due" while its setup page said a
first copy would be started within a few minutes. So `own` reads the stamp through
`backupstatus.own_stamp`, the page's own rule (not older than `[backup] since`): a success
that is not this install's is no success here, and the first copy is owed at once.

Only the config's key can disown a success (fc.D3). An install with no `[backup] since`
(one turned on before the key, a store set up by hand), or with one later than now, reads
`last_success` raw, as this watch always did. The page reads by the same rule (fc2.D7),
and nothing reads the job file's time: `keel backup install` writes that file again, and a
drain that believed it would start runs over a success that is this install's own.

Nothing is counted, started or said where the config names no store or no sets, and a
success forgets the whole count. `gather`, `line` and `problem` are the doctor's reading of
the same file; they write nothing.
"""

import json
import os
from datetime import datetime, timezone

from keel import backup

MARGIN_SECONDS = 15 * 60        # past the interval before the drain starts a run itself
OVERDUE_SECONDS = 3 * 3600      # this long since a success, awake, and the board says so
AWAKE_GAP_SECONDS = 5 * 60      # passes further apart than this: asleep, not counted
AWAKE_POLL_SHARE = 1.5          # or than this many of the drain's poll_seconds
AWAKE_PASS_SECONDS = 60         # plus this for the pass itself, if that is longer (`awake_gap`)
AWAKE_PASSES = 2                # passes in a row, each inside that gap, before a run is started
RETRY_SECONDS = 10 * 60         # a drain-started run that ended with no success: tried again after
STARTS_AN_HOUR = 3              # and the drain starts no more than this many in one interval
WATCH = "snapshot-watch.json"   # in backup_home: {success, awake, seen, passes, kicked, noticed}
NOTICE_KEY = "backup-stale"     # bin/keel-backup announce_broken, clear_broken


def written_here(cfg) -> bool:
    """This machine writes a backup: the config names a store and at least one set."""
    return bool(cfg.backup_store and cfg.backup_sets)


def clock(board) -> float:
    """The board's clock as seconds, so a test that pins the board pins this too."""
    return datetime.fromisoformat(board.now()).timestamp()


# ----- the count -----

NUMBERS = ("awake", "seen", "passes")       # and `kicked`, a list of them


def number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read(paths: backup.Paths) -> dict:
    """The watch as it was written, less anything that is not what this module writes: a
    file of garbage is an empty watch, and a field of the wrong type is a field not there.
    Nothing has to agree with this file, so nothing in it may stop a pass (r1.F4)."""
    try:
        watch = json.loads((paths.backup_home / WATCH).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(watch, dict):
        return {}
    kept = {key: watch[key] for key in NUMBERS if number(watch.get(key))}
    kicked = watch.get("kicked")
    kicked = kicked if isinstance(kicked, list) else [kicked]
    kept["kicked"] = [at for at in kicked if number(at)]
    if "success" in watch and (watch["success"] is None or isinstance(watch["success"], str)):
        kept["success"] = watch["success"]
    if isinstance(watch.get("noticed"), str) and watch["noticed"]:
        kept["noticed"] = watch["noticed"]
    return kept


def write(paths: backup.Paths, watch: dict) -> None:
    path = paths.backup_home / WATCH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(watch, sort_keys=True) + "\n")
    os.replace(tmp, path)


def forget(paths: backup.Paths) -> None:
    (paths.backup_home / WATCH).unlink(missing_ok=True)


def awake_gap(cfg) -> float:
    """How far apart two passes may be and still be one stretch awake: AWAKE_GAP_SECONDS,
    or a poll and a half of the drain's own `poll_seconds` plus a minute for the pass
    itself, where that is longer. A drain set to poll every 400 seconds never has two
    passes inside five minutes; with a fixed gap nothing was counted, its gate never
    opened and no run was ever started. Here that is 660 seconds.

    WHAT THIS DOES NOT COVER. Slow passes: the minute is all a pass is allowed, so a drain
    whose passes run for many minutes at a small `poll_seconds` still falls outside the
    gap, and counts and starts nothing (its own stall is the deck's health to say). And a
    `poll_seconds` of 560 or more puts the gap at fifteen minutes, which is how far apart
    a sleeping Mac's DarkWakes come: from there up, a drain's ordinary passes and one pass
    per DarkWake cannot be told apart, and a night asleep is counted as awake."""
    poll = getattr(cfg, "poll_seconds", 0)
    return max(AWAKE_GAP_SECONDS, AWAKE_POLL_SHARE * poll + AWAKE_PASS_SECONDS if number(poll) else 0)


def counted(watch: dict, stamp: str | None, now: float, within: float = AWAKE_GAP_SECONDS) -> dict:
    """The watch one pass later: the time since the last pass added when the drain was
    passing through it (`within`, `awake_gap`), and everything but the instant begun again
    for a new success."""
    if watch.get("success") != stamp:
        watch = {"success": stamp}
    gap = now - watch["seen"] if "seen" in watch else 0
    together = 0 < gap <= within
    # `passes`: how many in a row came inside the gap of the one before, this one included.
    # One alone is a DarkWake's single pass, or the first after the lid opens (r1.F2).
    return dict(watch, awake=watch.get("awake", 0) + (gap if together else 0), seen=now,
                passes=watch.get("passes", 1) + 1 if together else 1)


def overdue(watch: dict) -> bool:
    return watch.get("awake", 0) >= OVERDUE_SECONDS - backup.SNAPSHOT_SECONDS


# ----- the run -----

RUNNING = "a backup is running"


def held(paths: backup.Paths, watch: dict, age: float | None, now: float) -> str | None:
    """Why the drain starts no run this pass, or None when it does."""
    if backup.lock_live(paths, ".lock"):
        return RUNNING
    if age is not None and age <= backup.SNAPSHOT_SECONDS + MARGIN_SECONDS:
        return "not due"
    if watch.get("passes", 1) < AWAKE_PASSES:
        return "one pass is not yet a machine awake"
    recent = started(watch, now)
    if recent and now - recent[-1] < RETRY_SECONDS:
        return "started one within ten minutes"
    if len(recent) >= STARTS_AN_HOUR:
        return f"started {len(recent)} within the hour"
    return None


def started(watch: dict, now: float) -> list[float]:
    """When the drain started a run within the last interval, oldest first."""
    return sorted(at for at in watch.get("kicked", []) if 0 <= now - at < backup.SNAPSHOT_SECONDS)


def own_stamp(cfg, stamp: str | None, now: float | None = None) -> str | None:
    """`backupstatus.own_stamp`, asked for when it is needed: that module reads the kept
    readings (`keel/readiness.py`), whose rows read the doctor, which reads this one.
    `now`: the pass's own clock; the doctor's reading has none and takes the machine's."""
    from keel import backupstatus       # noqa: PLC0415 - the cycle the line above names
    at = None if now is None else datetime.fromtimestamp(now, timezone.utc)
    return backupstatus.own_stamp(cfg, stamp, at)


def own(cfg, paths: backup.Paths, now: float) -> tuple[str | None, float | None]:
    """`(stamp, age in seconds)` of this install's last success, `(None, None)` where the
    tool recorded none or the one on file is an earlier install's (the module's note)."""
    stamp = own_stamp(cfg, backup.state_stamp(paths, "last_success"), now)
    return (stamp, backup.state_age(paths, "last_success", now)) if stamp else (None, None)


def said(age: float | None) -> str:
    return "never succeeded" if age is None else f"last success {int(age // 3600)}h ago"


# ----- the pass -----

def upkeep(cfg, board, now: float | None = None) -> dict:
    """One pass: count, start a run when one is overdue, say so when none has succeeded.
    `{"started", "reason"}`, with `"notice"` (the card's id) on the pass that files one."""
    if not written_here(cfg):
        return {"started": False, "reason": "no backup is set up here"}
    paths = backup.paths_from(cfg, home=cfg.home)
    now = clock(board) if now is None else now
    stamp, age = own(cfg, paths, now)
    if age is not None and age <= backup.SNAPSHOT_SECONDS:
        forget(paths)
        return {"started": False, "reason": "not due"}
    watch = counted(read(paths), stamp, now, awake_gap(cfg))
    why = held(paths, watch, age, now)
    result = {"started": why is None, "reason": why or said(age)}
    watch["kicked"] = started(watch, now) + ([now] if why is None else [])
    # `kicked` reaches the file before the run, so a start that raises is not tried on
    # every pass. A home this cannot be written to starts nothing: nothing would bound the
    # starts, and the tool could record no success there either. The step fails, loudly.
    write(paths, watch)
    try:
        if why is None:
            backup.start(cfg, paths, backup.LABEL)
    finally:
        # THE RUN FIRST, THE CARD AFTER (r1.F3): saying so may fail, and must not cost the run
        # and never while a run holds the lock: it may be about to succeed (r1.F5)
        if why != RUNNING:
            result.update(tell(cfg, board, paths, watch))
    return result


# ----- the notice -----

TITLE = "No backup has succeeded in over 3 hours"


def brief(cfg, paths: backup.Paths, stamp: str | None) -> str:
    """Absolute times only, as the tool's own briefs are: the same words on every reading."""
    last = f"was {stamp}" if stamp else "has not happened yet"
    return (f"The last successful backup on {cfg.host} {last}. Runs have been started since and "
            f"none has succeeded, so everything changed since then exists only on this machine. "
            f"Check: keel backup status, and the log at {paths.logs / 'backup.out'}. "
            f"This card retires itself on the next successful run.")


def open_notice(board) -> str | None:
    """The open card under the tool's staleness key, whoever raised it."""
    for card in board.list_cards(include_archived=False):
        if card.get("stage") != "done" and (card.get("options") or {}).get("notice_key") == NOTICE_KEY:
            return card["id"]
    return None


def space_of(cfg) -> str:
    """Where the tool files its notices, else the first space the config has."""
    return "personal" if "personal" in cfg.spaces else next(iter(cfg.spaces))


def tell(cfg, board, paths: backup.Paths, watch: dict) -> dict:
    """File the notice when the count is overdue, once per missing success
    (`watch["noticed"]`): a card the user tapped away stays away, and one the tool already
    raised under the key is the one notice. `{"notice": id}` for a card filed on this call.

    Never raises: a board that will not take the card, or a file that will not take the
    mark, is `{"notice_failed": why}` and is tried again next pass. `noticed` is set only
    once the card exists, and a card filed whose mark was lost is found open next pass."""
    if not overdue(watch) or watch.get("noticed"):
        return {}
    filed = None
    try:
        there = open_notice(board)
        filed = None if there else board.create(
            space_of(cfg), TITLE, brief=brief(cfg, paths, watch.get("success")), autonomy="attended",
            topic="notice", options={"notice_key": NOTICE_KEY}, actor="drain")
        watch["noticed"] = there or filed
        write(paths, watch)
    except Exception as error:  # noqa: BLE001 - the card is one step; the run is the point
        return {"notice_failed": f"{type(error).__name__}: {error}", **({"notice": filed} if filed else {})}
    return {"notice": filed} if filed else {}


# ----- the doctor's reading -----

def gather(cfg) -> dict:
    """What the doctor says of the snapshot: whether this machine writes one, the last
    success as the tool stamped it, and whether the drain has counted it overdue."""
    if not written_here(cfg):
        return {"writes": False}
    paths = backup.paths_from(cfg, home=cfg.home)
    stamp = own_stamp(cfg, backup.state_stamp(paths, "last_success"))
    watch = read(paths)
    return {"writes": True, "last": stamp, "log": str(paths.logs / "backup.out"),
            "overdue": watch.get("success") == stamp and overdue(watch)}


def line(report: dict) -> str:
    if not report.get("writes"):
        return "backup        not set up here"
    last = f"last good run {report['last']}" if report.get("last") else "no successful run yet"
    return f"backup        {last}" + ("  OVERDUE" if report.get("overdue") else "")


def problem(report: dict) -> str | None:
    if not report.get("overdue"):
        return None
    last = f"since {report['last']}" if report.get("last") else "yet"
    # What the count holds, and no more: after a night asleep it is not three hours awake.
    return (f"backup: no successful run {last}, and over 2h awake with one owed "
            f"(keel backup status; the log is {report['log']})")
