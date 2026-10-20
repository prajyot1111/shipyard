"""Back up, from the first run (keel/backupsetup.py, c-678): a folder as the store, the keys,
the hourly job, and the passphrase shown once. On a real scratch install from `shipyard
init`, with the backup's own home in the temp directory (`KEEL_BACKUP_HOME`). The tool is a
fake executable that makes the key as the real one does and logs how it was called, so the
argv and the environment `run_tool` builds are the real ones; the service manager is a fake
whose load can fail as launchd's does. No real `bin/keel-backup`, no launchctl or systemctl,
and nothing outside the temp directory.

gpg is a fake too, in the one folder the test says the backup's jobs look in
(`backup.PATH_ENTRIES`), so a turn-on finds it on a machine that has none. The first copy
the turn-on starts (c-757) is the fake tool's `snapshot`, which records a success as the
real one does; each started run is waited for, so nothing here depends on timing."""

import json
import os
import stat
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from keel import actions, backup, backupsetup, firstrun, firstrunsteps, onboarding, packs, readiness
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

INSIDE = "That folder is inside the install, so the backup would copy itself."
# What `bin/keel-backup init` does that the setup reads: it makes the key where there is
# none, then (as the real one's listing can) fails where the test says so.
TOOL = """#!/bin/sh
here="$(dirname "$0")"
echo "argv=$* store=$KEEL_BACKUP_STORE sets=$KEEL_BACKUP_SETS home=$KEEL_HOME config=$KEEL_CONFIG" >> "$here/calls"
if [ -f "$here/fail-first" ]; then echo "keel-backup: could not list the store" >&2; exit 2; fi
key="$KEEL_BACKUP_HOME/backup.key"
if [ ! -s "$key" ]; then mkdir -p "$KEEL_BACKUP_HOME"; printf s3cret-passphrase > "$key"; fi
if [ -f "$here/fail-after-key" ]; then echo "keel-backup: could not write the store's README" >&2; exit 3; fi
if [ "$1" = snapshot ] && [ ! -f "$here/snapshot-quiet" ]; then
  # the time the test handed it (`stamp`), so no test compares a pinned time with a real one
  if [ -f "$here/stamp" ]; then at="$(cat "$here/stamp")"; else at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; fi
  printf '{"last_success": "%s"}' "$at" > "$KEEL_BACKUP_HOME/state.json"
fi
echo ready
"""
GPG = "#!/bin/sh\necho 'gpg (GnuPG) 2.4.7'\n"


class FakeManager:
    """A service manager with a state PER LABEL, kept as the real one keeps it: a folder of
    installed files (`installed_dir`, in the temp directory) and the set of labels that are
    running. `load` copies the job's file over the installed one and starts it, `unload`
    stops it and removes the installed file, as launchd's do (keel/service.py). It starts
    no real job. `fails` names the labels whose load answers as a bootstrap that failed."""

    def __init__(self, installed_dir: Path, kind: str = "launchd"):
        """`kind` is which manager's meaning of "loaded" this is (keel/service.py `state`):
        on launchd a job is loaded while it is bootstrapped, and a stop is a bootout, so a
        stopped job is not loaded. On systemd a job is loaded while its unit file is ENABLED,
        and a stop only stops the timer: the job stays enabled, so it still reads as loaded."""
        self.installed_dir, self.kind = installed_dir, kind
        self.fails, self.loaded, self.unloaded, self.kept, self.stopped, self.running = set(), [], [], [], [], set()

    def files(self, svc):
        # the file names its install, as the real one carries KEEL_CONFIG
        return {f"{svc.label}.plist": f"<plist>{svc.label} {dict(svc.env).get('KEEL_CONFIG')}</plist>".encode()}

    def write(self, svc, etc):
        etc.mkdir(parents=True, exist_ok=True)
        for name, content in self.files(svc).items():
            (etc / name).write_bytes(content)
        return [etc / name for name in self.files(svc)]

    def load(self, svc, etc):
        self.installed_dir.mkdir(parents=True, exist_ok=True)
        for name in self.files(svc):
            (self.installed_dir / name).write_bytes((etc / name).read_bytes())
        self.running.discard(svc.label)             # the real one boots the label out first
        if svc.label in self.fails:
            print(f"Bootstrap failed: 5: Input/output error ({svc.label})")
            return 5
        self.loaded.append(svc.label)
        self.running.add(svc.label)
        return 0

    def stop(self, svc):
        """Stopped, and left installed: what the real one's bootout without an unlink is."""
        self.stopped.append(svc.label)
        if self.kind == "launchd":
            self.running.discard(svc.label)
        return True, ""

    def unload(self, svc, keep=False):
        """Everything the real one does to take a job out (a bootout on launchd, disable and
        stop on systemd), and, unless `keep`, its installed file removed."""
        (self.kept if keep else self.unloaded).append(svc.label)
        self.running.discard(svc.label)
        for name in ([] if keep else self.files(svc)):
            (self.installed_dir / name).unlink(missing_ok=True)
        return []

    def state(self, label, scheduled=False):
        return label in self.running, None

    def others(self, label: str, running: bool) -> Path:
        """Another install's job for `label`, as it sits in the manager's folder."""
        self.installed_dir.mkdir(parents=True, exist_ok=True)
        path = self.installed_dir / f"{label}.plist"
        path.write_bytes(f"<plist>{label} /another/install/config.toml</plist>".encode())
        if running:
            self.running.add(label)
        return path


class Case(unittest.TestCase):
    KIND = "launchd"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.home = self.dir / "install"
        self.own = self.dir / "backup-home"
        patch = mock.patch.dict(os.environ, {"KEEL_BACKUP_HOME": str(self.own)})
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        readiness.forget()
        self.addCleanup(readiness.forget)
        self.assertEqual(init(self.home), 0)
        self.fake = self.dir / "fake-bin"
        self.fake.mkdir()
        tool = self.fake / "keel-backup"
        tool.write_text(TOOL)
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        (self.fake / "gpg").write_text(GPG)
        (self.fake / "gpg").chmod(0o755)
        self.manager = FakeManager(self.dir / "manager-jobs", self.KIND)
        for name, value in (("tool", tool), ("manager", self.manager)):
            patched = mock.patch.object(backup.Paths, name, new_callable=mock.PropertyMock, return_value=value)
            patched.start()
            self.addCleanup(patched.stop)
        self.looks_in(self.fake, "/usr/bin", "/bin")
        self.started, real = [], backup.start

        def start(cfg, paths, key):
            """The detached start, waited for: the run has ended before the test reads."""
            proc = real(cfg, paths, key)
            self.started.append(key)
            proc.wait()
            return proc
        waited = mock.patch.object(backup, "start", start)
        waited.start()
        self.addCleanup(waited.stop)

    def looks_in(self, *entries) -> None:
        """Where the backup's jobs look for a program (and so where gpg is looked for)."""
        patched = mock.patch.object(backup, "PATH_ENTRIES", tuple(str(entry) for entry in entries))
        patched.start()
        self.addCleanup(patched.stop)
        readiness.forget()

    @property
    def ran(self) -> list[str]:
        calls = self.fake / "calls"
        return calls.read_text().splitlines() if calls.is_file() else []

    @property
    def loaded(self) -> list[str]:
        return self.manager.loaded

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def on(self, folder, at: datetime | None = None):
        """The page's verb. `at`: the board's clock, pinned, which is when the turn-on says
        it happened (`[backup] since`)."""
        cfg = self.cfg()
        with open_board(cfg) as board:
            if at is not None:
                board.now = lambda: at.isoformat(timespec="seconds")
            return actions.act(cfg, board, {"verb": "firstrun.backup.on", "folder": str(folder)})


class FolderTest(Case):
    def test_the_suggested_folder_is_in_the_users_home(self):
        with mock.patch.dict(os.environ, {"HOME": "/srv/sam"}):
            self.assertEqual(backupsetup.suggested(), "/srv/sam/shipyard-backup")

    def test_a_folder_with_files_and_no_key_for_them_is_refused(self):
        """What is in it cannot be this computer's backup, and a turn-on that fails could not
        be taken back out of a folder that was not empty (review F4)."""
        folder = self.dir / "copies"
        folder.mkdir()
        (folder / "holiday.jpg").write_text("x")
        with self.assertRaisesRegex(actions.ActionError, "is not empty") as caught:
            self.on(folder)
        self.assertEqual(caught.exception.detail["kind"], "used")
        self.assertEqual((self.ran, self.cfg().backup_store), ([], None))
        self.assertEqual([path.name for path in folder.iterdir()], ["holiday.jpg"])

    def test_a_folder_inside_the_install_is_refused_with_the_suggested_one(self):
        before = (self.home / "config.toml").read_text()
        with self.assertRaises(actions.ActionError) as caught:
            self.on(self.home / "state" / "copies")
        self.assertEqual(str(caught.exception), INSIDE)
        self.assertEqual(caught.exception.detail, {"kind": "inside", "suggested": backupsetup.suggested()})
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertEqual(self.ran, [])

    def test_the_install_itself_is_inside_too(self):
        with self.assertRaisesRegex(actions.ActionError, "inside the install"):
            self.on(self.home)

    def test_a_folder_must_be_a_whole_path(self):
        for text in ("", "copies", "./copies"):
            with self.subTest(text), self.assertRaisesRegex(actions.ActionError, "whole path"):
                self.on(text)

    def test_a_folder_that_cannot_be_made_is_said(self):
        blocker = self.dir / "a-file"
        blocker.write_text("x")
        with self.assertRaisesRegex(actions.ActionError, "cannot be written"):
            self.on(blocker / "copies")
        self.assertIsNone(self.cfg().backup_store)


class TurnOnTest(Case):
    def test_turn_on_names_the_folder_makes_the_keys_and_starts_the_jobs(self):
        folder = self.dir / "copies"
        done = self.on(folder)
        cfg = self.cfg()
        self.assertEqual((cfg.backup_store, cfg.backup_sets), (f"file:{folder}", ["keel"]))
        self.assertTrue(folder.is_dir())
        said = f"store=file:{folder} sets=keel home={cfg.root} config={self.home / 'config.toml'}"
        self.assertEqual(self.ran, [f"argv=init {said}", f"argv=snapshot {said}"],
                         "init ran on the new config, then the first copy was started (c-757)")
        self.assertEqual(self.loaded, [backup.LABEL, backup.VERIFY_LABEL])
        written = sorted(path.name for path in (self.home / "services").iterdir())
        self.assertEqual(len(written), len(set(written)))
        self.assertTrue(all(name.startswith("dev.shipyard.backup") for name in written), written)
        self.assertEqual(done["passphrase"], "s3cret-passphrase")
        self.assertEqual(done["folder"], str(folder))

    def test_a_key_this_computer_already_had_is_not_shown_again(self):
        self.own.mkdir()
        (self.own / "backup.key").write_text("an-older-key")
        done = self.on(self.dir / "copies")
        self.assertIsNone(done["passphrase"])
        self.assertTrue(done["kept_key"])

    def test_a_setup_that_fails_puts_the_config_back(self):
        before = (self.home / "config.toml").read_text()
        (self.fake / "fail-first").write_text("")
        with self.assertRaisesRegex(actions.ActionError, "could not list the store"):
            self.on(self.dir / "copies")
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertEqual(self.loaded, [])

    def refused(self, folder=None):
        with self.assertRaises(actions.ActionError) as caught:
            self.on(folder or self.dir / "copies")
        return caught.exception

    def nothing_is_left(self, before: str) -> None:
        """All or nothing (review F4): the config as it was, no job left loaded, no key whose
        passphrase was never shown, and a store folder with nothing of this try in it."""
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertEqual(sorted(self.manager.unloaded), sorted(self.manager.loaded + list(self.manager.fails)))
        self.assertFalse((self.own / "backup.key").exists(), "a key nobody was shown is not left")
        self.assertEqual(list((self.dir / "copies").iterdir()), [])
        self.assertEqual(list((self.home / "services").glob("dev.shipyard.backup*")), [])

    def test_a_setup_that_fails_after_it_made_the_key_takes_the_key_back(self):
        before = (self.home / "config.toml").read_text()
        (self.fake / "fail-after-key").write_text("")
        self.assertIn("could not write the store's README", str(self.refused()))
        self.nothing_is_left(before)
        (self.fake / "fail-after-key").unlink()
        self.assertEqual(self.on(self.dir / "copies")["passphrase"], "s3cret-passphrase", "a retry starts clean")

    def test_an_hourly_job_that_will_not_load_turns_nothing_on(self):
        before = (self.home / "config.toml").read_text()
        self.manager.fails = {backup.LABEL}
        refused = self.refused()
        self.assertEqual(refused.detail["kind"], "job")
        self.assertIn("so nothing was turned on", str(refused))
        self.assertIn("Input/output error", str(refused))
        self.nothing_is_left(before)
        self.manager.fails = set()
        done = self.on(self.dir / "copies")
        self.assertEqual(done["passphrase"], "s3cret-passphrase", "the retry makes its key and shows it")
        self.assertEqual(self.cfg().backup_store, f"file:{self.dir / 'copies'}")

    def test_a_weekly_job_that_will_not_load_takes_the_hourly_one_back_out(self):
        before = (self.home / "config.toml").read_text()
        self.manager.fails = {backup.VERIFY_LABEL}
        # the hourly job ran once as it loaded and wrote its first copy into the store
        real = self.manager.load

        def load(svc, etc):
            if svc.label == backup.LABEL:
                (self.dir / "copies" / "sets").mkdir()
            return real(svc, etc)
        self.manager.load = load
        self.assertEqual(self.refused().detail["kind"], "job")
        self.assertEqual(self.manager.loaded, [backup.LABEL])
        self.assertIn(backup.LABEL, self.manager.unloaded)
        self.nothing_is_left(before)

    def test_a_key_that_was_there_before_is_never_taken_away(self):
        self.own.mkdir()
        (self.own / "backup.key").write_text("an-older-key")
        self.manager.fails = {backup.LABEL}
        self.assertEqual(self.refused().detail["kind"], "job")
        self.assertEqual((self.own / "backup.key").read_text(), "an-older-key")
        self.assertIsNone(self.cfg().backup_store)

    def notice(self) -> str:
        """The card the real tool stages a new key's passphrase on, as it makes the key."""
        with open_board(self.cfg()) as board:
            return board.create("personal", "Put the Keel backup passphrase in your password manager",
                                brief="s3cret-passphrase", actor="drain", options={"notice_key": "backup-passphrase"})

    def staging(self):
        """The hourly load, made to stage the passphrase card first: what the tool did during
        this call."""
        made, real = [], self.manager.load

        def load(svc, etc):
            if not made:
                made.append(self.notice())
            return real(svc, etc)
        self.manager.load = load
        return made

    def test_the_passphrase_card_of_a_key_that_was_taken_back_is_closed(self):
        made = self.staging()
        self.manager.fails = {backup.LABEL}
        self.refused()
        with open_board(self.cfg()) as board:
            self.assertEqual(board.get(made[0])["stage"], "done")

    def test_a_passphrase_card_from_before_this_call_is_left_open(self):
        """It closed every open passphrase card, the user's unread one included (review r2.F11)."""
        earlier = self.notice()
        made = self.staging()
        self.manager.fails = {backup.LABEL}
        self.refused()
        with open_board(self.cfg()) as board:
            self.assertNotEqual(board.get(earlier)["stage"], "done", "not this call's to close")
            self.assertEqual(board.get(made[0])["stage"], "done")

    def test_one_file_that_cannot_be_removed_does_not_keep_the_key_or_hide_the_refusal(self):
        """The folder and the key were taken back outside any guard (review r2.F11): one
        OSError left the key, with a passphrase nobody was shown, and answered a server error."""
        before = (self.home / "config.toml").read_text()
        made = self.staging()
        stuck = self.dir / "copies" / "stuck.bin"
        real = self.manager.load

        def load(svc, etc):
            stuck.write_text("x")
            return real(svc, etc)
        self.manager.load = load
        self.manager.fails = {backup.LABEL}
        unlink = Path.unlink

        def refusing(path, *args, **rest):
            if path == stuck:
                raise PermissionError(13, "Operation not permitted")
            return unlink(path, *args, **rest)
        with mock.patch.object(Path, "unlink", refusing):
            refused = self.refused()
        self.assertEqual(refused.detail["kind"], "job", "the refusal, not the error of taking it back")
        self.assertFalse((self.own / "backup.key").exists(), "the key nobody was shown is still taken back")
        self.assertEqual((self.home / "config.toml").read_text(), before)
        with open_board(self.cfg()) as board:
            self.assertEqual(board.get(made[0])["stage"], "done")

    def test_the_finders_own_file_in_the_folder_is_left_alone(self):
        folder = self.dir / "copies"
        folder.mkdir()
        (folder / ".DS_Store").write_text("finder")
        self.manager.fails = {backup.LABEL}
        self.refused()
        self.assertEqual([path.name for path in folder.iterdir()], [".DS_Store"])

    def test_a_folder_that_cannot_be_listed_is_not_taken_for_empty(self):
        folder = self.dir / "copies"
        folder.mkdir()
        iterdir = Path.iterdir

        def refusing(path):
            if path == folder:
                raise PermissionError(13, "Permission denied")
            return iterdir(path)
        with mock.patch.object(Path, "iterdir", refusing):
            self.assertEqual(self.refused().detail["kind"], "used")
        self.assertEqual((self.ran, self.cfg().backup_store), ([], None))

    def untouched(self, path: Path, label: str, running: bool, before: str) -> None:
        """Another install's job as it was, and nothing of this install written."""
        self.assertEqual(path.read_bytes(), f"<plist>{label} /another/install/config.toml</plist>".encode())
        self.assertEqual(label in self.manager.running, running)
        self.assertEqual((self.manager.loaded, self.manager.unloaded, self.ran), ([], [], []))
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertFalse((self.dir / "copies").exists(), "refused before any write")
        self.assertFalse((self.home / "services").exists() and list((self.home / "services").glob("dev.shipyard.backup*")))

    def test_another_installs_backup_job_is_never_replaced(self):
        before = (self.home / "config.toml").read_text()
        path = self.manager.others(backup.LABEL, running=True)
        with self.assertRaisesRegex(actions.ActionError, "already runs a Shipyard backup"):
            self.on(self.dir / "copies")
        self.untouched(path, backup.LABEL, True, before)

    def test_another_installs_weekly_job_is_never_replaced(self):
        """Only the hourly label was asked about (review r2.F5): the weekly one was written
        over on success, and removed when the turn-on failed."""
        before = (self.home / "config.toml").read_text()
        path = self.manager.others(backup.VERIFY_LABEL, running=True)
        self.assertEqual(self.refused().detail["kind"], "other")
        self.untouched(path, backup.VERIFY_LABEL, True, before)

    def test_another_installs_job_that_is_installed_and_not_loaded_is_never_replaced(self):
        """`launchctl list` says nothing of a job whose file is installed and booted out."""
        for label in (backup.LABEL, backup.VERIFY_LABEL):
            with self.subTest(label=label):
                before = (self.home / "config.toml").read_text()
                path = self.manager.others(label, running=False)
                self.assertEqual(self.refused().detail["kind"], "other")
                self.untouched(path, label, False, before)
                path.unlink()

    def test_a_job_under_the_old_labels_that_is_loaded_is_another_backup(self):
        """r1.F12: a machine whose backup was installed as dev.keel.backup before c-729 (here
        another install's, loaded) is still found by the one-backup-per-user check: refused,
        and nothing of this install written."""
        old = backup.OLD_LABELS[backup.LABEL]
        before = (self.home / "config.toml").read_text()
        path = self.manager.others(old, running=True)
        self.assertEqual(self.refused().detail["kind"], "other")
        self.untouched(path, old, True, before)

    def test_a_failed_turn_on_under_the_old_labels_keeps_the_old_installed_file(self):
        """r1.F12: this install's own hourly job, installed under the old label and not loaded
        by an earlier turn: the turn-on runs under the old labels (`backup.label_of`), and when
        it fails it takes back only what it brought, so the old file stays as it was."""
        old, old_verify = backup.OLD_LABELS[backup.LABEL], backup.OLD_LABELS[backup.VERIFY_LABEL]
        self.manager.installed_dir.mkdir(parents=True)
        (self.manager.installed_dir / f"{old}.plist").write_bytes(b"<plist>placeholder</plist>")
        cfg = self.cfg()
        job = backup.service(backup.paths_from(cfg), backup.LABEL)
        self.assertEqual(job.label, old, "a machine with the old jobs keeps their labels")
        for name, content in self.manager.files(job).items():
            (self.manager.installed_dir / name).write_bytes(content)
        installed = (self.manager.installed_dir / f"{old}.plist").read_bytes()
        before = (self.home / "config.toml").read_text()
        self.manager.fails = {old_verify}
        self.assertEqual(self.refused().detail["kind"], "job")
        self.assertEqual(self.manager.unloaded, [old_verify], "only the label this call brought")
        self.assertEqual((self.manager.installed_dir / f"{old}.plist").read_bytes(), installed)
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertNotIn(old, self.manager.running)

    def test_a_loaded_job_is_another_backup_whoevers_file_it_is(self):
        self.manager.running = {backup.VERIFY_LABEL}
        self.assertEqual(self.refused().detail["kind"], "other")
        self.assertEqual((self.manager.loaded, self.manager.unloaded, self.ran), ([], [], []))

    def test_a_job_file_that_was_installed_before_is_not_taken_out_by_a_failed_turn_on(self):
        """This install's own file, left installed and not loaded by an earlier turn: the call
        did not make it, so the call does not remove it."""
        cfg = self.cfg()
        job = backup.service(backup.paths_from(cfg), backup.LABEL)
        self.manager.installed_dir.mkdir(parents=True)
        for name, content in self.manager.files(job).items():
            (self.manager.installed_dir / name).write_bytes(content)
        installed = (self.manager.installed_dir / f"{backup.LABEL}.plist").read_bytes()
        before = (self.home / "config.toml").read_text()
        self.manager.fails = {backup.VERIFY_LABEL}
        self.assertEqual(self.refused().detail["kind"], "job")
        self.assertEqual(self.manager.unloaded, [backup.VERIFY_LABEL], "only the label this call brought")
        self.assertEqual((self.manager.installed_dir / f"{backup.LABEL}.plist").read_bytes(), installed)
        # each job is as it was before the call (fix check r2.D3): the hourly one was not
        # loaded, so it is not left loaded, and the next turn-on is not "another install"
        self.assertEqual(self.manager.running, set(), "not loaded before, not loaded after")
        self.assertEqual((self.manager.kept, self.manager.stopped), ([backup.LABEL], []),
                         "taken out the manager's own way, its file kept")
        self.assertFalse((self.manager.installed_dir / f"{backup.VERIFY_LABEL}.plist").exists())
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.manager.fails = set()
        self.assertEqual(self.on(self.dir / "copies")["folder"], str(self.dir / "copies"), "a retry is not refused")

    def test_a_backup_that_is_on_is_not_turned_on_elsewhere(self):
        self.on(self.dir / "copies")
        with self.assertRaisesRegex(actions.ActionError, "already on"):
            self.on(self.dir / "other")

    def test_the_readiness_row_says_backup_is_on_and_nothing_about_copies(self):
        """r1.F10: the row said "the board is backed up to ..." on a named store alone, beside
        a step that can say no copy has been written."""
        self.assertEqual(readiness.backup_row(self.cfg())["why"], "no backup is set up: the board lives only in this install")
        (self.fake / "snapshot-quiet").write_text("")
        self.on(self.dir / "copies")
        self.assertEqual(readiness.backup_row(self.cfg()),
                         {"ready": True, "why": f"backup is on, into file:{self.dir / 'copies'}", "step": "backup"})

    def test_the_passphrase_is_answered_whatever_the_first_copys_start_does(self):
        """r1.F11: the start sat before the answer and caught OSError alone, so any other
        error failed the verb with the backup on and the passphrase never shown."""
        with mock.patch.object(backup, "start", side_effect=ValueError("embedded null byte")):
            done = self.on(self.dir / "copies")
        self.assertEqual((done["passphrase"], done["started"]), ("s3cret-passphrase", False))
        self.assertEqual(done["note"], f"backup is on, into {self.dir / 'copies'}")
        self.assertEqual(self.cfg().backup_store, f"file:{self.dir / 'copies'}")

    def test_it_is_a_config_verb_so_the_deck_reads_the_store(self):
        self.assertIn("firstrun.backup.on", onboarding.CONFIG_VERBS)


class SystemdTurnOnTest(TurnOnTest):
    """Every turn-on test again, on a manager where "loaded" means enabled and a stop leaves
    the job enabled (fix check r2.D3): a job put back with a stop alone still reads as loaded
    there, and the next turn-on is refused as another install's."""
    KIND = "systemd"


class StatusTest(Case):
    def test_off_says_so_with_the_suggested_folder(self):
        found = backupsetup.status(self.cfg())
        self.assertEqual((found["on"], found["suggested"]), (False, backupsetup.suggested()))

    def test_on_says_the_three_checks(self):
        """What each row says in each of its states is `tests/test_backupfirst.py` (c-757)."""
        folder = self.dir / "copies"
        (self.fake / "snapshot-quiet").write_text("")       # the run the turn-on starts records nothing
        turned_on = datetime(2026, 10, 3, 4, 0, tzinfo=timezone.utc)
        self.on(folder, at=turned_on)
        found = backupsetup.status(self.cfg())
        self.assertEqual((found["on"], found["folder"]), (True, str(folder)))
        self.assertTrue(found["writable"])
        self.assertIsNone(found["first"])
        self.assertEqual((found["proof"]["state"], found["proof"]["at"]), ("waiting", None))
        # what the page needs to say "No copy yet" and where to look (review r2.F14)
        self.assertEqual(found["log"], str(self.own / "logs" / "backup.out"))
        self.assertEqual(found["key"], str(self.own / "backup.key"))
        self.assertEqual(found["since"], "2026-10-03T04:00:00+00:00", "the turn-on's own time, from the config (r1.F5)")
        (self.own / "state.json").write_text(json.dumps({"last_success": "2026-10-07T10:00:00Z",
                                                        "last_verify": "2026-10-11T04:30:00Z"}))
        found = backupsetup.status(self.cfg())
        self.assertEqual(found["first"], "2026-10-07T10:00:00+00:00")
        self.assertEqual(found["proof"]["at"], "2026-10-11T04:30:00+00:00")

    def test_a_folder_that_went_away_is_not_writable(self):
        folder = self.dir / "copies"
        self.on(folder)
        folder.rmdir()
        self.assertFalse(backupsetup.status(self.cfg())["writable"])


class StepTest(Case):
    def test_the_step_follows_the_browser_step(self):
        ids = [step.id for step in firstrun.STEPS]
        self.assertEqual(ids[ids.index("browser") + 1], "backup")
        self.assertEqual(firstrun.BY_ID["backup"].headline, "Keep a copy of your board")
        self.assertIn("backup", packs.SETUP_AFTER)

    def test_it_is_done_once_the_backup_is_on(self):
        done, why, extra = firstrunsteps.backup_state(self.cfg(), {}, None)
        self.assertEqual((done, extra["backup"]["on"]), (False, False))
        self.assertEqual(why, "no backup is set up: the board lives only in this install")
        self.on(self.dir / "copies")
        done, why, extra = firstrunsteps.backup_state(self.cfg(), {}, None)
        self.assertTrue(done)
        self.assertEqual(why, f"backup is on, and the first copy is written, into {self.dir / 'copies'}")


if __name__ == "__main__":
    unittest.main()
