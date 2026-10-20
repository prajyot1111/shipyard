"""`keel backup`: the two scheduled jobs for the encrypted off-machine copy, and the verbs
that drive it.

The tool itself is `bin/keel-backup`, a bash script moved into Keel by cutover step 8 and
left in bash on purpose: it is a pipeline of `tar`, `gzip`, `gpg`, `git` and `gh`, every
promise it makes is about how those behave, and it carries its own proof in
`bin/keel-backup-selftest`. Rewriting it in Python would have translated a hardened script
into an unhardened one to satisfy a rule about `keel/`, which is a module rule, not a
reason to throw away the reasoning in 1,800 lines of comments.

So what lives here is what Keel needs to know and do about the service, the same split as
`keel/voice.py`:

    install [--load]   write the hourly snapshot job (dev.shipyard.backup) and the weekly
                       restore proof (dev.shipyard.backup-verify) into etc/: launchd plists on
                       macOS, systemd `.service` plus `.timer` pairs on Linux
                       (`keel/service.py`); `--load` copies them where the manager looks
                       and starts them
    uninstall          stop them all and remove the manager's copies
    status             the jobs' state, then the tool's own status
    run [args]         one snapshot now, attended (the hourly agent runs the same thing)
    verify [args]      one restore proof now (the weekly agent runs the same thing)
    pull               one nightly copy of the store now (dev.shipyard.backup-pull runs it)
    init | migrate     the tool's `init` and `migrate-from-git`, attended, once
    slim [args]        rewrite the retained snapshots without what the backup now leaves out
                       (`--dry-run`, then `--approved`; `--restore ID`,
                       `--purge [--id ID | --unproven ID]`; `--set N`, `--limit N`, `--json`; the
                       sums are `keel/backupslim.py`)
    env                the config's backup settings as shell exports, which is how a bare
                       `bin/keel-backup` finds the store and this host's sets

A machine with `[backup] pull = true` gets a third job, the nightly pull at 03:00, and its
drain starts the same pull whenever it is due and the machine is awake (`pull_upkeep`).
The drain also starts an hourly snapshot the service manager did not, and says so on the
board when none has succeeded for two waking hours with one owed (`keel/backupdue.py`,
c-750).
Which sets this machine writes, and where the store is, are the config's (`[backup]`
`store` and `sets`); the tool is handed them rather than holding its own copy.

Nothing here parses the tool's output or reimplements its rules. `run` and `verify` are
pass-throughs so a person gets the tool's exit code and its own words, which are the ones
written to be read at 4am.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from keel import config as config_module, service as service_module

# THE JOBS ARE NAMED AS THE INSTALL'S OTHER UNITS ARE (c-729, `appservices.PREFIX`): a
# stranger's install showed dev.keel.backup beside dev.shipyard.deck and .drain. These are
# also the keys the tables below use. A machine whose jobs were installed under the old
# labels keeps them (`label_of`), so a backup that runs is never renamed out from under it.
LABEL = "dev.shipyard.backup"
VERIFY_LABEL = "dev.shipyard.backup-verify"
# EVERY INSTALLED PATH IS RELATIVE TO `Paths.home`, not to `~` (`keel/service.py` holds
# them now). `Paths` already carries the home it is built against, and resolving the
# LaunchAgents directory against the process's real one instead meant that
# `tests/test_backup.py` wrote into, and then DELETED, the live agents in
# `~/Library/LaunchAgents` on every `make test` run: the uninstall test removed
# both installed plists for real, so the agents survived only until the next
# reboot. Found 2026-09-18, with both plists already gone and both labels still
# loaded. A path that reaches outside the Paths object is a path a test cannot
# point somewhere safe.
SNAPSHOT_SECONDS = 3600         # the hourly agent; the tool skips a run whose content is unchanged
# Sunday at 04:30. StartCalendarInterval rather than StartInterval: a weekly interval
# counted from load would drift with every reboot, and launchd runs a missed calendar job
# once on wake, which is the behaviour wanted on a laptop that is asleep at 04:30. On
# systemd the same dict becomes `OnCalendar=Sun *-*-* 04:30:00` with `Persistent=true`.
VERIFY_WHEN = {"Weekday": 0, "Hour": 4, "Minute": 30}
PULL_LABEL = "dev.shipyard.backup-pull"
# 03:00 every night, calendar-based for the same reason as the verify: a laptop asleep at
# 03:00 runs it once on wake, which is the whole point of a nightly second copy.
PULL_WHEN = {"Hour": 3, "Minute": 0}
# THE PULL ALSO RUNS FROM THE DRAIN, WHEN IT IS DUE (c-440). The 03:00 job fires in one of
# the Mac's DarkWakes, freezes between them, and finishes hours later on a stale listing.
# The drain passes only while the Mac is awake, so `pull_upkeep` starts the pull from there
# once the last good one is older than PULL_DUE_HOURS, under `caffeinate -i` so an idle
# sleep does not cut it off, and at most once per PULL_RETRY_SECONDS so a failing pull is
# not restarted on every half-minute pass. The 03:00 job stays as a backstop; the pull's
# own lock makes the two exclusive.
PULL_DUE_HOURS = 20
PULL_RETRY_SECONDS = 3600
PULL_KICKED = "pull-kicked"     # in backup_home: when the drain last started a pull
LABELS = (LABEL, VERIFY_LABEL, PULL_LABEL)
OLD_LABELS = {LABEL: "dev.keel.backup", VERIFY_LABEL: "dev.keel.backup-verify", PULL_LABEL: "dev.keel.backup-pull"}
OLD_FAMILY = "dev.keel.backup"
WHAT = {LABEL: "hourly snapshot", VERIFY_LABEL: "weekly restore proof", PULL_LABEL: "nightly pull"}
VERB = {LABEL: "snapshot", VERIFY_LABEL: "verify", PULL_LABEL: "pull"}
LOG = {LABEL: "backup", VERIFY_LABEL: "verify", PULL_LABEL: "pull"}
# launchd and systemd hand a job almost no environment, and the tool shells out to rclone
# and gpg, which live in Homebrew's prefix on the Mac. `python3` is needed too, for the
# board snapshot and for `bin/keel backup env`.
PATH_ENTRIES = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")


@dataclass
class Paths:
    root: Path
    home: Path
    # The config the jobs read (c-622): the one `keel backup install` was run with, so the
    # keel set's board is that config's state dir and not whatever the checkout's own
    # the config names. None: the jobs find the config as any `keel` does.
    config: Path | None = None
    # Where its service file is rendered (c-722, `Config.services_dir`): the install's
    # `services/`. None: the checkout's `etc/`.
    services: Path | None = None

    @property
    def tool(self) -> Path:
        return self.root / "bin" / "keel-backup"

    @property
    def backup_home(self) -> Path:
        """Where the working clone, the passphrase, the state file and the logs live.

        Deliberately outside every checkout and outside every backed-up set: an untracked
        file inside a checkout dirties the tree, and a passphrase inside `state/` would
        ride along in the archive it unlocks. `KEEL_BACKUP_HOME` overrides it, which is
        how the selftest points the whole thing at a fabricated tree."""
        override = os.environ.get("KEEL_BACKUP_HOME")
        return Path(override).expanduser() if override else self.home / ".keel-backup"

    @property
    def logs(self) -> Path:
        return self.backup_home / "logs"

    @property
    def etc(self) -> Path:
        return self.services or self.root / "etc"

    @property
    def manager(self) -> service_module.Manager:
        return service_module.Manager(self.home)


def paths_from(cfg, home: Path | None = None) -> Paths:
    source = getattr(cfg, "source", None)
    return Paths(root=cfg.root, home=home or Path.home(), config=Path(source) if source else None,
                 services=getattr(cfg, "services_dir", None))


# ----- the jobs -----

def environment(paths: Paths) -> dict[str, str]:
    env = {
        "PATH": os.pathsep.join(PATH_ENTRIES),
        "HOME": str(paths.home),
        "KEEL_HOME": str(paths.root),
    }
    if paths.config is not None:
        env["KEEL_CONFIG"] = str(paths.config)
    return env


def kept_old(paths: Paths) -> bool:
    """This machine's backup jobs were installed under the labels before c-729: a file of
    the old family where the service manager loads from, or where they are rendered."""
    for where in (paths.manager.installed_dir, paths.etc):
        try:
            if any(where.glob(OLD_FAMILY + "*")):
                return True
        except OSError:
            continue
    return False


def label_of(paths: Paths, key: str) -> str:
    """The label one job runs under on this machine: the old one where the old jobs are
    installed, else the install's own (`key`)."""
    return OLD_LABELS[key] if kept_old(paths) else key


def service(paths: Paths, label: str) -> service_module.Service:
    """One of the three jobs, which differ in four fields and nothing else: the verb, the
    schedule, whether loading the job runs it at once, and the log. `label` is the job's
    key (`LABEL`, `VERIFY_LABEL`, `PULL_LABEL`); what it runs under is `label_of`."""
    snapshot = label == LABEL
    return service_module.Service(
        label=label_of(paths, label),
        description="Shipyard backup: " + WHAT[label],
        argv=[str(paths.tool), VERB[label]],
        cwd=paths.root,
        env=environment(paths),
        # NOT under state/logs. state/ is in the keel set, and a log an hourly job appends
        # to would be a file inside the archive that changes on every run. It also keeps
        # the rule the tool's own rotate_log assumes: the log lives beside the work files.
        stdout=paths.logs / f"{LOG[label]}.out",
        stderr=paths.logs / f"{LOG[label]}.err",
        keep_alive=False,
        run_at_load=snapshot,
        interval=SNAPSHOT_SECONDS if snapshot else None,
        calendar=None if snapshot else dict(VERIFY_WHEN if label == VERIFY_LABEL else PULL_WHEN),
    )


def render_plist(paths: Paths, label: str) -> bytes:
    return service_module.plist(service(paths, label))


def installed_labels(pull: bool) -> tuple[str, ...]:
    """The jobs this host runs: the pull only where `backup_pull` says so."""
    return LABELS if pull else (LABEL, VERIFY_LABEL)


def install(paths: Paths, load: bool = False, pull: bool = False) -> int:
    if not paths.tool.exists():
        print(f"keel backup install: no {paths.tool}", file=sys.stderr)
        return 2
    labels = installed_labels(pull)
    for label in labels:
        for written in paths.manager.write(service(paths, label), paths.etc):
            print(f"wrote {written}")
    if not load:
        print("not loaded; `keel backup install --load` when ready")
        return 0
    codes = [paths.manager.load(service(paths, label), paths.etc) for label in labels]
    return max(codes)


def uninstall(paths: Paths) -> int:
    """All three, whatever this host's config says now: a pull job installed before
    `backup_pull` was turned off is still a job to stop."""
    for label in LABELS:
        for removed in paths.manager.unload(service(paths, label)):
            print(f"stopped and removed {removed} (the copy in {paths.etc} is kept)")
    return 0


# ----- the jobs, from the drain: the pull here, the snapshot in `keel/backupdue.py` -----

def state_stamp(paths: Paths, key: str) -> str | None:
    """One of the tool's `state.json` stamps as it wrote it (`2026-10-09T19:35:45Z`), None
    when it was never written or cannot be read."""
    try:
        stamp = json.loads((paths.backup_home / "state.json").read_text()).get(key)
    except (OSError, ValueError, AttributeError):
        return None
    return stamp if isinstance(stamp, str) and stamp else None


def state_age(paths: Paths, key: str, now: float) -> float | None:
    """Seconds since one of the tool's `state.json` stamps (`last_success`, `last_pull`),
    None when it was never written or cannot be read."""
    try:
        when = datetime.strptime(state_stamp(paths, key), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return now - when.timestamp()


def lock_live(paths: Paths, name: str) -> bool:
    """One of the tool's own locks (`.lock` for a snapshot, `.pull-lock` for a pull) is
    held by a live process. The lock is a symlink whose target is the holder's pid
    (`lock_take`); a directory with a `pid` file is the tool's older lock, from a run
    across a deploy, and is read too. Only a pid above 0 names a run, as the tool's own
    test has it: to `kill`, 0 and below are process groups, and 0 is the caller's own,
    always there."""
    lock = paths.backup_home / name
    try:
        pid = int(os.readlink(lock) if lock.is_symlink() else (lock / "pid").read_text().strip())
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (OSError, ValueError, OverflowError):
        return False
    return True


def tool_argv(paths: Paths, verb: str) -> list[str]:
    """One of the tool's verbs, kept awake by `caffeinate -i` where there is one (macOS)."""
    caffeinate = shutil.which("caffeinate")
    return ([caffeinate, "-i"] if caffeinate else []) + [str(paths.tool), verb]


def start(cfg, paths: Paths, key: str) -> subprocess.Popen:
    """Start one of the jobs (`key`: its label), detached, with its output appended to the
    logs the scheduled job writes. Never waits on it: the tool writes its own logs, takes
    its own lock and raises its own alarms. The ONE way Keel starts a run itself: the drain's
    pull and its overdue snapshot, and the first copy of a backup just turned on
    (`backupsetup.first_copy`, c-757). The process is handed back for a caller that has a
    reason to wait (the suite); none of those three does."""
    paths.logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, **environment(paths), **settings(cfg))
    with open(paths.logs / f"{LOG[key]}.out", "a") as out, open(paths.logs / f"{LOG[key]}.err", "a") as err:
        return subprocess.Popen(tool_argv(paths, VERB[key]), stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                cwd=paths.root, env=env, start_new_session=True)


def pull_upkeep(cfg, now: float | None = None) -> dict:
    """Start the pull, detached, when this host pulls and the last good one is older than
    PULL_DUE_HOURS. Never waits on it: the pull writes its own logs and its own alarms."""
    if not cfg.backup_pull:
        return {"started": False, "reason": "this host does not pull"}
    now = time.time() if now is None else now
    paths = paths_from(cfg, home=cfg.home)
    age = state_age(paths, "last_pull", now)
    if age is not None and age < PULL_DUE_HOURS * 3600:
        return {"started": False, "reason": "not due"}
    if lock_live(paths, ".pull-lock"):
        return {"started": False, "reason": "a pull is running"}
    kicked = paths.backup_home / PULL_KICKED
    if kicked.exists() and now - kicked.stat().st_mtime < PULL_RETRY_SECONDS:
        return {"started": False, "reason": "started one within the hour"}
    paths.logs.mkdir(parents=True, exist_ok=True)
    kicked.touch()
    os.utime(kicked, (now, now))
    start(cfg, paths, PULL_LABEL)
    said = "never pulled" if age is None else f"last pull {int(age // 3600)}h ago"
    return {"started": True, "reason": said}


# ----- status -----

def agent_lines(paths: Paths, pull: bool = False) -> list[str]:
    """A scheduled job is normally loaded with no pid: it is not running right now, which
    is not the same as not installed."""
    lines = []
    for key in installed_labels(pull):
        label = label_of(paths, key)
        loaded, pid = paths.manager.state(label, scheduled=True)
        state = "loaded" if loaded else "NOT LOADED"
        lines.append(f"{label}: {state} ({WHAT[key]})" + (f", running as pid {pid}" if pid else ""))
    return lines


def status(paths: Paths, cfg, argv: list[str]) -> int:
    for line in agent_lines(paths, cfg.backup_pull):
        print(line)
    print()
    return tool(paths, ["status", *argv], cfg)


# ----- the settings the tool is handed -----

def settings(cfg) -> dict[str, str]:
    """The config's backup settings in the tool's own variable names. The store is empty
    when `[backup] store` is absent, which the tool reports as "not set up" rather than
    guessing one."""
    values = {
        "KEEL_BACKUP_STORE": cfg.backup_store or "",
        "KEEL_BACKUP_SETS": " ".join(cfg.backup_sets),
        # this install's own sets (c-722): the tool knows Keel's two and these
        "KEEL_BACKUP_EXTRA": " ".join(getattr(cfg, "backup_extra", None) or []),
        "KEEL_BACKUP_HOST": cfg.host,
        "KEEL_BACKUP_PULL": "1" if cfg.backup_pull else "0",
        # the keel set's board: this install's own, wherever its state dir is (c-622)
        "KEEL_BACKUP_STATE_DIR": str(cfg.state_dir),
    }
    if cfg.backup_rclone_config:
        values["KEEL_BACKUP_RCLONE_CONFIG"] = str(cfg.backup_rclone_config)
    if getattr(cfg, "backup_legacy_repo", None):
        values["KEEL_BACKUP_LEGACY_REPO"] = cfg.backup_legacy_repo
    return values


def env_lines(cfg) -> list[str]:
    """`export NAME='value'` lines a shell can eval."""
    return [f"export {name}={shlex.quote(value)}" for name, value in settings(cfg).items()]


# ----- the tool -----

def tool(paths: Paths, argv: list[str], cfg=None) -> int:
    """Run `bin/keel-backup`, inheriting stdout and stderr. The tool's own words and its
    own exit code reach the caller; nothing here parses or rewords them."""
    if not paths.tool.exists():
        print(f"keel backup: no {paths.tool}", file=sys.stderr)
        return 2
    # Flushed first, or Python's block buffering on a pipe puts everything printed here
    # AFTER everything the child wrote, so `keel backup status` reads back to front.
    sys.stdout.flush()
    env = dict(os.environ, KEEL_HOME=str(paths.root), **(settings(cfg) if cfg else {}))
    return subprocess.run([str(paths.tool), *argv], env=env).returncode


# ----- parser -----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel backup",
                                     description="the encrypted off-machine copy of everything that exists once")
    subs = parser.add_subparsers(dest="verb", required=True)
    sub = subs.add_parser("install")
    sub.add_argument("--load", action="store_true",
                     help="also start them under launchd (macOS) or systemd (Linux)")
    subs.add_parser("uninstall")
    subs.add_parser("status")
    subs.add_parser("env", help="the config's backup settings as shell exports")
    subs.add_parser("run", help="one snapshot now (the hourly agent runs the same thing)")
    subs.add_parser("verify", help="one restore proof now (the weekly agent runs the same thing)")
    subs.add_parser("pull", help="one copy of the store into the mirror now (the nightly job)")
    subs.add_parser("init", help="prove the store is reachable and make the keys, once")
    subs.add_parser("migrate", help="the one-off move off the old GitHub repo")
    subs.add_parser("slim", help="rewrite old snapshots without what the backup now leaves out")
    return parser


PASS_THROUGH = {"run": "snapshot", "verify": "verify", "status": "status", "pull": "pull",
                "init": "init", "migrate": "migrate-from-git", "slim": "slim"}


def main(argv: list[str] | None = None) -> int:
    """`run`, `verify`, `status`, `pull`, `init` and `migrate` hand everything after the verb
    to the tool unparsed, so
    `keel backup run --force --set keel` reaches it whole rather than being refused by a
    parser here that would have to know every flag the tool has. `install` and `uninstall`
    are Keel's own, so they go through the parser and an unknown verb meets its usage."""
    argv = list(argv or [])
    cfg = config_module.load()
    paths = paths_from(cfg)
    verb, rest = (argv[0] if argv else ""), argv[1:]
    if verb in PASS_THROUGH:
        if verb == "status":
            return status(paths, cfg, rest)
        return tool(paths, [PASS_THROUGH[verb], *rest], cfg)
    args = build_parser().parse_args(argv)
    if args.verb == "env":
        print("\n".join(env_lines(cfg)))
        return 0
    if args.verb == "install":
        return install(paths, load=args.load, pull=cfg.backup_pull)
    return uninstall(paths)
