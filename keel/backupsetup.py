"""Back up, turned on from the first run (c-678): one verb, a folder as the store.

`bin/keel-backup` and `keel/backup.py` already do the work (Atlas 85): an encrypted
snapshot of the board every hour, a restore proof every week, into a store that is either
an rclone remote or a plain folder (`file:<dir>`). Setting that up took a terminal. This is
the page's one verb for the folder form, and what the step shows afterwards.

`turn_on(cfg, folder)` (`firstrun.backup.on`), in order, each step refusing before the next:

1. the folder: a whole path, never inside the install ("That folder is inside the install,
   so the backup would copy itself."), empty unless this computer already holds a backup
   key (what is in it then is this computer's store), made if it is not there, and written
   to once;
2. nothing is replaced: a config that already names a store is refused, and so is a
   computer whose backup job is already loaded for another install (the jobs' labels are
   one per user account, `keel/backup.py`);
3. the config: `[backup] store = "file:<folder>"`, `sets = ["keel"]` and `since`, when this
   turn-on happened (the board's clock, in UTC), in one checked and backed-up edit
   (`setupconfig.edit`). `since` is how the step and the drain tell this install's copies
   from an earlier install's on the same account (`keel/backupstatus.py`, r1.F5);
4. the keys: the tool's own `init`, which proves the store and makes the passphrase where
   this computer has none;
5. the jobs: the hourly snapshot and the weekly restore proof, written under the
   install's `services/` and loaded (`start_jobs`);
6. the first copy (c-757, `first_copy`): one snapshot started now, by this call, and never
   waited for.

**gpg first** (c-757). Every snapshot is encrypted with gpg, and the tool's `init` needs
only openssl, so a computer with no gpg was turned on and then wrote no copy, ever. The
turn-on asks the check of Check this computer (`prereqs.gpg_check`, read afresh) before
anything is written, and refuses with a pointer at that step's row (`detail`: `kind` "gpg",
`step` "prerequisites").

**The first copy is the turn-on's own start.** It was left to the service manager, which
runs the hourly job as it is loaded on launchd and not at all on a manager that does not,
and the page said "writing it now" either way. `first_copy` starts it with `backup.start`,
the detached start the drain already uses for the nightly pull and for an overdue snapshot
(`keel/backupdue.py`): one way to start a run, under the tool's own lock, so a run the
service manager started in the same second and this one cannot both write (the loser says
the lock is held and exits 0). The request does not wait: a first copy takes seconds to
minutes, and what happened to it is the step's to read (`keel/backupstatus.py`). A start
that cannot be made does not undo the turn-on: the backup is on, the step says no copy is
being written, and the drain starts the next one. It is the LAST thing the call does
(r1.F11): the answer, with the passphrase shown once, is built first, and whatever the
start raises is `started: False`, never a failed verb with the backup on.

**All or nothing** (review F4). A failure in step 4 or 5 puts back everything this call
made (`undo`): the config's text, each job it loaded or tried to (`Manager.unload`, and the
files it wrote under `services/`), what it put into a folder that was empty, and the key
when THIS call made it, with the notice card the tool staged its passphrase on. A key that
was there before is never touched. So no state is left where a key exists and its
passphrase was never shown, and the next tap starts clean.

The answer carries the passphrase ONCE, and only when this call made it: a key this
computer already had was shown when it was made, and is not read back to a page again.

What the step shows afterwards is `keel/backupstatus.py` (`status`, here too under its
old name): the folder, the first copy as it is observed, the proof, and whose they are.

Another backup's job is never touched (`jobs_before`): both labels are asked about before
anything is written, and `undo` unloads only a label this call brought.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from keel import backup, backupstatus, cloneerrors, configedit
from keel import config as config_module
from keel.backupstatus import FILE, KEY, SERVICES, since, status, store_folder, suggested  # noqa: F401
from keel.board import Refused as BoardRefused
from keel.setupconfig import SetupError, edit, install_of

TOOL_SECONDS = 300
INSIDE = "That folder is inside the install, so the backup would copy itself."
OTHER = ("This computer already runs a Shipyard backup for another install, and there is one backup "
         "job per user account. Turn that one off first (`keel backup uninstall` there).")
NOTE = "Turned on in the deck's first run (docs/atlas/85-backup.md): a folder as the store."
USED = ("That folder is not empty, and this computer has no backup key for what is in it. "
        "Pick an empty folder.")
JOB = "The backup's {which} job could not be started, so nothing was turned on: {said}"
WHICH = {backup.LABEL: "hourly", backup.VERIFY_LABEL: "weekly"}
NOTICE_KEY = "backup-passphrase"       # `key_card` in bin/keel-backup: the card a new passphrase is staged on
IGNORED = (".DS_Store",)


class Refused(SetupError):
    def __init__(self, said: str, detail: dict | None = None):
        super().__init__(said)
        self.detail = detail


def folder_of(cfg, text: str) -> Path:
    """The folder the user named, as a whole path outside the install."""
    home = install_of(cfg).resolve()
    text = (text or "").strip()
    path = Path(text).expanduser()
    if not text or not path.is_absolute():
        raise Refused("The backup folder needs its whole path, for example " + suggested())
    path = path.resolve()
    if path == home or home in path.parents:
        raise Refused(INSIDE, {"kind": "inside", "suggested": suggested()})
    return path


def make(folder: Path) -> None:
    """The folder made, and written to once, or `Refused` with why."""
    probe = folder / ".keel-backup-probe"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe.write_text("")
        probe.unlink()
    except OSError as error:
        raise Refused(f"{folder} cannot be written: {error.strerror or error}", {"kind": "folder"}) from None


def run_tool(paths: backup.Paths, cfg, argv: list[str]) -> tuple[int, str]:
    """`bin/keel-backup <argv>` with the config's settings: `(exit code, its last line)`."""
    env = dict(os.environ, KEEL_HOME=str(paths.root), **backup.settings(cfg))
    if paths.config is not None:
        env["KEEL_CONFIG"] = str(paths.config)
    try:
        done = subprocess.run([str(paths.tool), *argv], env=env, capture_output=True, text=True,
                              errors="replace", stdin=subprocess.DEVNULL, timeout=TOOL_SECONDS)
    except subprocess.TimeoutExpired:
        return 124, f"keel-backup {' '.join(argv)} did not finish in {TOOL_SECONDS}s"
    except OSError as error:
        return 127, str(error)
    return done.returncode, cloneerrors.last_line(done.stderr or done.stdout)


def named(text: str, folder: Path, at: str) -> str:
    """The config with the backup turned on: the store, the set, and `since`, when (`at`)."""
    text = configedit.set_entry(text, "backup", "store", f"{FILE}{folder}")
    text = configedit.set_entry(text, "backup", "sets", ["keel"])
    return configedit.set_entry(text, "backup", "since", at)


def clock(board) -> str:
    """Now, in UTC to the second: the board's clock where there is a board, so a test that
    pins the board pins the turn-on's time too."""
    at = datetime.fromisoformat(board.now()) if board is not None else datetime.now()
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def holds(folder: Path) -> bool:
    """Whether the folder has anything in it (the Finder's own file aside). A folder that is
    not there yet holds nothing; one that cannot be listed counts as holding something
    (review r2.F11), since a failed turn-on could not take its own files back out of it."""
    try:
        return any(entry.name not in IGNORED for entry in folder.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return False        # not there, or under a file: `make` says why it cannot be made
    except OSError:
        return True


def jobs_before(paths: backup.Paths, manager) -> dict[str, bool]:
    """`{label: was it there}` for the hourly and the weekly job, asked before anything is
    written, or `Refused` when one of them is another backup's (review r2.F5).

    There is one backup job per user account, under fixed labels. Loading a job copies this
    install's file over the installed one and stops whatever ran under the label, and
    unloading removes the installed file (`keel/service.py`), so another install's job
    would be replaced on success and removed on failure. So for EACH label: a job that is
    loaded is refused, and so is an installed file whose bytes are not this install's own
    rendering. That comparison, not a path in the file: the rendering carries the install's
    config path, while the code checkout and the tool can be shared by two installs.

    A label is `there` when a file was installed (it can only be this install's own by
    now); `undo` takes back out only the labels that were not."""
    there = {}
    for label in (backup.LABEL, backup.VERIFY_LABEL):
        if manager.state(backup.label_of(paths, label), scheduled=True)[0]:
            raise Refused(OTHER, {"kind": "other"})
        found = False
        for name, ours in manager.files(backup.service(paths, label)).items():
            installed = manager.installed_dir / name
            try:
                theirs = installed.read_bytes()
            except FileNotFoundError:
                continue
            except OSError:
                raise Refused(OTHER, {"kind": "other"}) from None       # there, and not ours to read
            if theirs != ours:
                raise Refused(OTHER, {"kind": "other"})
            found = True
        there[backup.label_of(paths, label)] = found
    return there


def notices(board) -> set[str]:
    """The ids of the open cards a new key's passphrase is staged on."""
    if board is None:
        return set()
    return {card["id"] for card in board.list_cards(include_archived=False)
            if card.get("stage") != "done" and (card.get("options") or {}).get("notice_key") == NOTICE_KEY}


def turn_on(cfg, folder_text: str, board=None) -> dict:
    """`firstrun.backup.on` {folder}: the store named, the keys made, the jobs started, or
    nothing at all (`undo`)."""
    folder = folder_of(cfg, folder_text)
    if cfg.backup_store:
        raise Refused(f"Backup is already on, into {store_folder(cfg) or cfg.backup_store}.")
    if not backupstatus.gpg(fresh=True)["ok"]:     # before any write: no copy could ever be made
        raise Refused(backupstatus.NO_GPG, {"kind": "gpg", "step": "prerequisites"})
    paths = backup.paths_from(cfg)
    manager = paths.manager
    there = jobs_before(paths, manager)         # before any write: another backup's job is never touched
    open_before = notices(board)
    key = paths.backup_home / KEY
    had_key = key.is_file() and key.stat().st_size > 0
    was_empty = not holds(folder)
    if not was_empty and not had_key:
        raise Refused(USED, {"kind": "used"})
    make(folder)
    before = Path(cfg.source).read_text()
    at = clock(board)
    done = edit(cfg, lambda text: named(text, folder, at))
    new = config_module.load(Path(cfg.source), ensure=False)
    tried: list = []        # the jobs this call wrote and asked the manager to load
    try:
        code, said = run_tool(paths, new, ["init"])
        if code != 0:
            raise Refused("The backup could not be set up, so nothing was turned on: "
                          f"{said or f'keel-backup init exited {code}'}", {"kind": "init"})
        start_jobs(paths, manager, install_of(cfg) / SERVICES, tried)
    except BaseException:
        undo(new, before, manager, there, tried, install_of(cfg) / SERVICES,
             folder if was_empty else None, None if had_key else key, board, open_before)
        raise
    answer = {**done, "folder": str(folder), "kept_key": had_key, "started": False,
              "passphrase": None if had_key else read(key), "key": str(key),
              "note": f"backup is on, into {folder}"}
    if first_copy(new, paths):          # last: the answer above is whole whatever this does
        answer.update(started=True, note=f"backup is on: the first copy is being written to {folder}")
    return answer


def first_copy(cfg, paths: backup.Paths) -> bool:
    """The first snapshot, started now and never waited for (the module's note): whether
    the start was made. What became of the run is `backupstatus.status`'s to read."""
    try:
        backup.start(cfg, paths, backup.LABEL)
    except Exception:  # noqa: BLE001 - the backup is on; a start that raised anything is a start not made
        return False
    return True


def start_jobs(paths: backup.Paths, manager, into: Path, tried: list) -> None:
    """The hourly snapshot and the weekly proof, written under the install (`services/`, as
    the app's own services are, `keel/appservices.py`) and loaded. Never into the code's
    `etc/`: an install's jobs carry its paths, and the code may not be the user's to write.
    Each job is put on `tried` before its load is asked for, so `undo` takes out one that
    failed half way too. The first that will not load is the refusal."""
    for label in backup.installed_labels(False):
        job = backup.service(paths, label)
        tried.append(job)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            manager.write(job, into)
            code = manager.load(job, into)
        if code != 0:
            said = cloneerrors.last_line(printed.getvalue()) or f"exit {code}"
            raise Refused(JOB.format(which=WHICH.get(label, label), said=said), {"kind": "job"})


def undo(cfg, before: str, manager, there: dict, tried: list, services: Path, folder: Path | None,
         key: Path | None, board=None, open_before: set | None = None) -> None:
    """Everything a failed turn-on made, taken back; EACH part on its own (its own guard), so
    one that cannot be undone does not keep the others, and nothing here raises over the
    refusal that brought it.

    EACH JOB IS PUT BACK TO HOW IT WAS BEFORE THE CALL (fix check r2.D3). No job was loaded
    before (`jobs_before` refuses one that is), so every job this call tried ends not
    loaded: a job whose file this call installed is unloaded, which removes that file, and a
    job whose file was installed before (`there`) is unloaded with its file kept
    (`Manager.unload(job, keep=True)`), which is "installed, not loaded" on launchd and on
    systemd alike. `Manager.stop` is not used: on systemd it leaves the job enabled, which
    reads as loaded. So a retry is never refused as another install's backup. `tried` is every job this
    call wrote under the install's `services/`. `folder` is the store when it was empty
    before this call, `key` the key file when this call made it (else None: not ours), and
    `open_before` the passphrase cards that were open before it, which are not this call's
    to close."""
    for job in reversed(tried):
        with contextlib.suppress(OSError, subprocess.SubprocessError), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            manager.unload(job, keep=bool(there.get(job.label)))
    for job in reversed(tried):
        for name in manager.files(job):
            with contextlib.suppress(OSError):
                (services / name).unlink(missing_ok=True)
    with contextlib.suppress(SetupError, OSError):
        edit(cfg, lambda text: before)
    if folder is not None:
        empty(folder)
    if key is not None:
        with contextlib.suppress(OSError):
            key.unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            retire_notice(board, open_before or set())


def empty(folder: Path) -> None:
    """What a failed turn-on left in a store folder that was empty before it, removed: each
    entry on its own, and never the Finder's own file, which was there before."""
    try:
        entries = [entry for entry in folder.iterdir() if entry.name not in IGNORED]
    except OSError:
        return
    for entry in entries:
        with contextlib.suppress(OSError):
            shutil.rmtree(entry, ignore_errors=True) if entry.is_dir() and not entry.is_symlink() \
                else entry.unlink(missing_ok=True)


def retire_notice(board, open_before: set) -> None:
    """The card the tool staged this call's new key's passphrase on, closed: that key is
    gone. A card that was open before the call is another key's, or the user's unread one,
    and is left (review r2.F11)."""
    for card_id in sorted(notices(board) - set(open_before)):
        with contextlib.suppress(BoardRefused):
            board.stage(card_id, "done", "human",
                        note="the backup was not turned on, so this key was taken back out")


def read(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except OSError:
        return None
