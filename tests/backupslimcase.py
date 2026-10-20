"""The fixture of the `keel backup slim` tests (c-724): a scratch store, scratch keys and a
scratch backup home under one temporary directory, and the real `bin/keel-backup` run
against them.

The snapshots in that store are written here directly, in the old shape: a whole tree,
tarred and encrypted, with the logs, the drafts, the `node_modules`, the film and the
scratch folder the scan leaves out today still inside. `SlimCase` is that store and the
ways a test runs the tool on it; `MidReplace` is a store as a run stopped mid-replace
leaves it. Not a test module: `tests/test_backupslim*.py` import it.
"""

import atexit
import hashlib
import io
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import ROOT

TOOL = ROOT / "bin" / "keel-backup"
GPG = shutil.which("gpg")
RCLONE = shutil.which("rclone")
# macOS tar is bsdtar, which folds `._name` members into `name` and refuses names that
# are not UTF-8; GNU tar unpacks both as they are.
BSDTAR = "bsdtar" in subprocess.run(["tar", "--version"], capture_output=True, text=True).stdout



# The clock is read here, once, and nowhere else: every id a backup test makes is placed
# from it, by `day` and `hours_ago`.
_NOW = datetime.now(timezone.utc)


def day(ago: int, hour: int = 0) -> str:
    """The id of a snapshot taken `ago` days back, at `hour` that day."""
    return (_NOW - timedelta(days=ago)).strftime("%Y%m%d") + f"T{hour:02d}0000Z"


def hours_ago(hours: int) -> str:
    """The id of a snapshot taken that many hours back, to the second."""
    return (_NOW - timedelta(hours=hours)).strftime("%Y%m%dT%H%M%SZ")


def _ids() -> tuple[str, str, str, str]:
    """The fixture's snapshot ids, placed by TODAY (r3.F3). The tool's retention reads the
    clock, and several tests run the real hourly job over these snapshots, so fixed ids
    would start being pruned on some date and the tests would fail from that day on.
    The keel set keeps hourly snapshots for a day and one a day to thirty days (c-752), so
    all four sit in the daily tier, days clear of both its edges at any time of day.
    OLD and NEW are two separate days of the last week, each its day's only snapshot, so
    retention keeps both. EARLY and LATE are one day, ten days back, where it keeps only
    the later: the pair for the tests that want a prune."""
    return day(3), day(2), day(10), day(10, 1)


OLD, NEW, EARLY, LATE = _ids()
FILM = os.urandom(1_500_000)        # does not compress, so the store's megabytes move

# What an old snapshot holds, and the rule that leaves each dropped file out today, spelled
# as the tool's own find spells it.
KEPT = {
    "state/cards/c-1/plan.md": b"the plan\n",
    "state/cards/c-1/evidence.log": b"a log that is the card's evidence\n",
    "state/voice/transcript.jsonl": b'{"said": "hello"}\n',
    "segments/daybook/data/items.json": b'{"items": []}\n',
    "config.toml": b"[machine]\n",
    "odd/keep.txt": b"under no root the scan walks today\n",
    # Staged, not scanned (r2.F12): a repo's history rides as a bundle beside the board.
    "repos/memory.bundle": b"# v2 git bundle\n",
}
DROPPED = {
    "state/logs/keel.out.log": ("state/logs", b"keel up\n" * 40),
    "state/drafts/demo/take.txt": ("state/drafts", b"a draft\n"),
    "state/cards/c-1/merged-tests.log": ("merged-tests.log", b"ok\n" * 300),
    "state/cards/c-1/out/film.MP4": ("*.mp4", FILM),
    "state/cards/c-1/out/node_modules/pkg/index.js": ("node_modules", b"module.exports = 1\n"),
    "state/voice/cache/0a1b.bin": ("state/voice/cache", b"a clip\n"),
    # A card's scratch folder goes whole (c-752): a checkout, plain copies, a house's notes.
    "state/cards/c-1/scratch/web/src/app.js": ("state/cards/*/scratch", b"console.log(1)\n"),
    "state/cards/c-1/scratch/copy/src/app.js": ("state/cards/*/scratch", b"console.log(2)\n"),
    "state/cards/c-1/scratch/notes/n.md": ("state/cards/*/scratch", b"a house's notes\n"),
}
KEPT_DIRS = ("segments/daybook/data/inbox",)
DROPPED_DIRS = ("state/fetch-locks",)
SCRATCH = "state/cards/c-1/scratch"
# The tool's own gpg line. The s2k count is said out loud: left to its default, gpg starts
# an agent to calibrate one, and a test must not leave a daemon behind.
ENCRYPT = ("gpg --batch --yes --quiet --no-tty --pinentry-mode loopback --symmetric "
           "--cipher-algo AES256 --s2k-mode 3 --s2k-digest-algo SHA512 --s2k-count 65011712 "
           '--compress-algo none --passphrase-file "$2" -o "$3"')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def by_rule(files=DROPPED) -> dict:
    """{rule: (files, bytes)} of one old snapshot."""
    out: dict = {rule: (0, 0) for rule in DROPPED_DIRS}     # an empty directory, dropped by name
    for rule, data in files.values():
        count, size = out.get(rule, (0, 0))
        out[rule] = (count + 1, size + len(data))
    return out


# ----- built once a process, and handed out as copies -----
#
# A slim test is a handful of runs of the real tool, and each run is a second or two of
# `gpg`, `tar` and a few dozen short processes. Most of those runs are a prelude many tests
# share: the same snapshots published, shown by the dry run, rewritten, or killed at a step.
# So three things are made once in a process and copied after that:
#
#   the board         one small SQLite file
#   a snapshot        the standard old tree, tarred and encrypted, per id
#   a run of `slim`   WHAT THE TOOL DID, keyed by everything it read (`SlimCase.tool`)
#
# The third is the one that needs saying. A run of `bin/keel-backup slim` reads its
# arguments, its environment, the store, the backup home, the live tree and the temp root,
# and writes the store, the home and the temp root. The first time a test makes a run, the
# tool really runs, and what it left is kept. A later run whose every input is the same
# (`SlimCase.inputs` says exactly what is compared: the tool's own text, what was asked,
# and every entry's path, kind, permission bits and bytes; not modification times) gets a
# copy of what the tool left that first time, and its exit code and output. Nothing is asserted on anything the tool did not really produce from those very
# inputs; a run with any input its own (a stub on PATH, a changed tool, a lock held by a
# live process, an edited file) is made for real.
# Set, every run is made for real: the way to check that reuse hides nothing, at about
# twice the time.
EVERY_RUN = "SLIM_TESTS_EVERY_RUN"
_FIXTURES = tempfile.TemporaryDirectory(prefix="keel-slim-fixtures.")
atexit.register(_FIXTURES.cleanup)
_BLOBS: dict = {}
_MID: dict = {}
_RUNS: dict = {}
_TEXTS: dict = {}
_ROOT = b"<the test's own root>"


def _tool_text(tool: Path) -> str:
    """A digest of the tool as it is written: the script, and the modules it runs from the
    checkout it sits in. Once a process for each tool a test runs."""
    if tool not in _TEXTS:
        sha = hashlib.sha256(tool.read_bytes())
        for module in sorted((tool.resolve().parent.parent / "keel").glob("backupslim*.py")):
            sha.update(module.name.encode() + b"\0" + module.read_bytes())
        _TEXTS[tool] = sha.hexdigest()
    return _TEXTS[tool]


def _board() -> Path:
    path = Path(_FIXTURES.name) / "board.db"
    if not path.exists():
        db = sqlite3.connect(path)
        db.execute("create table cards (id text primary key, title text)")
        db.execute("insert into cards values ('c-1', 'a card that exists nowhere else')")
        db.commit()
        db.close()
    return path


@unittest.skipUnless(GPG, "gpg is not installed")
class SlimCase(unittest.TestCase):
    STORE_KIND = "file"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.live, self.home = self.root / "install", self.root / "backup-home"
        self.store, self.scratch = self.root / "store", self.root / "tmp"
        for made in (self.live, self.home, self.store, self.scratch):
            made.mkdir()
        self.key = self.home / "backup.key"
        self.key.write_text("a scratch passphrase")
        self.conf = self.root / "rclone.conf"
        self.conf.write_text("[scratch]\ntype = local\n")
        self.board = self.root / "board.db"
        shutil.copy(_board(), self.board)
        self.tree_is_standard = False

    # ----- the scratch store -----

    def env(self, **extra) -> dict:
        store = f"file:{self.store}" if self.STORE_KIND == "file" else f"rclone:scratch:{self.store}"
        env = dict(os.environ, KEEL_HOME=str(self.live), KEEL_BACKUP_HOME=str(self.home),
                   KEEL_BACKUP_STORE=store, KEEL_BACKUP_SETS="keel", KEEL_BACKUP_EXTRA="",
                   KEEL_BACKUP_HOST="scratch", KEEL_BACKUP_PULL="0",
                   KEEL_BACKUP_RCLONE_CONFIG=str(self.conf), TMPDIR=str(self.scratch),
                   KEEL_BACKUP_SLIM_DISK_FLOOR_MB="16", KEEL_BACKUP_SLIM_LOCK_WAIT="0")
        env.pop("KEEL_BACKUP_STATE_DIR", None)
        env.update(extra)
        return env

    def tool(self, *argv, **extra):
        """One run of the tool. A `slim` run whose every input was seen before in this
        process is not made again: see the note above `_RUNS`."""
        reuse = argv[:1] == ("slim",) and not {"PATH", "TMPDIR"} & set(extra) and not os.environ.get(EVERY_RUN)
        key = self.inputs(argv, extra) if reuse else None
        if key in _RUNS:
            return self.replay(*_RUNS[key])
        done = subprocess.run(["bash", str(TOOL), *argv], env=self.env(**extra),
                              capture_output=True, text=True, errors="replace", timeout=300)
        if key:
            self.keep(key, done)
        return done

    def read_and_written(self) -> tuple:
        return (("store", self.store), ("home", self.home), ("tmp", self.scratch))

    def inputs(self, argv, extra) -> str | None:
        """The key a `slim` run is reused under. What it holds:

        - the store's kind, the tool's path, and THE TOOL'S OWN TEXT: a digest of the
          script and of the `keel/backupslim*.py` modules beside it (`_tool_text`);
        - what was asked: each flag with the value it takes, in any order;
        - the environment a test added for this run (the rest is the fixture's, the same
          for every run in the process);
        - under the store, the backup home, the temp root and the live tree: every entry's
          path, its kind and its permission bits; every file's bytes; every link's target
          and whether it is old enough for the tool to break as a stale lock.

        The test's own root is written out of paths and contents, so two tests' identical
        stores are one input. NOT in the key: modification times, other than that one fact
        about a link. A copied fixture is always newer than the one it was copied from, so
        with them in the key no run would ever match another; and the slim reads no time
        but a lock's. None when something cannot be read."""
        root = os.fsencode(str(self.root))
        # The arguments as what they ask for, not the order they came in: each flag with
        # the value it takes.
        asked, rest = [], list(argv)
        while rest:
            flag = rest.pop(0)
            asked.append((flag, rest.pop(0) if flag in ("--set", "--limit", "--restore", "--unproven", "--id") and rest else None))
        sha = hashlib.sha256(repr((self.STORE_KIND, str(TOOL), _tool_text(TOOL), sorted(asked, key=repr),
                                   sorted(extra.items()))).encode().replace(root, _ROOT))
        try:
            for label, top in self.read_and_written() + (("live", self.live),):
                for here, dirs, files in os.walk(top):
                    dirs.sort()
                    rel = os.path.relpath(here, top)
                    for name in sorted(dirs + files):
                        path = os.path.join(here, name)
                        status = os.lstat(path)
                        sha.update(f"\0{label}\0{rel}\0{name}\0{status.st_mode:o}\0".encode("utf-8", "surrogateescape"))
                        if stat.S_ISLNK(status.st_mode):
                            # A lock: whom it names, and whether it is old enough to break.
                            sha.update(os.fsencode(os.readlink(path)) + (b"\0aged" if status.st_mtime < 1e9 else b"\0young"))
                        elif stat.S_ISREG(status.st_mode):
                            sha.update(hashlib.sha256(Path(path).read_bytes().replace(root, _ROOT)).digest())
        except OSError:
            return None
        return sha.hexdigest()

    def keep(self, key: str, done) -> None:
        kept = Path(tempfile.mkdtemp(dir=_FIXTURES.name))
        try:
            for label, top in self.read_and_written():
                shutil.copytree(top, kept / label, symlinks=True)
        except (OSError, shutil.Error):
            return                          # something unreadable was left: this run is not reused
        _RUNS[key] = (kept, str(self.root), done)

    def replay(self, kept: Path, was_root: str, done):
        """What the tool left the first time it was given these inputs, under this test's
        own root: the three trees copied, and that test's root written out of the output
        and out of what the home and the temp root say (a killed run records where its
        unpacked work is)."""
        old, new = os.fsencode(was_root), os.fsencode(str(self.root))
        for label, top in self.read_and_written():
            shutil.rmtree(top)
            shutil.copytree(kept / label, top, symlinks=True)
        for top in (self.home, self.scratch):
            for path in top.rglob("*"):
                if path.is_file() and not path.is_symlink() and path.stat().st_size < 1 << 20:
                    data = path.read_bytes()
                    if old in data:
                        times = path.stat()
                        path.write_bytes(data.replace(old, new))
                        os.utime(path, ns=(times.st_atime_ns, times.st_mtime_ns))
        return subprocess.CompletedProcess(done.args, done.returncode, done.stdout.replace(was_root, str(self.root)),
                                           done.stderr.replace(was_root, str(self.root)))

    def dry(self, *argv) -> dict:
        """The dry run, which is also what writes the approval file the rewrite needs."""
        done = self.tool("slim", "--set", "keel", "--json", "--dry-run", *argv)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def rewrite(self, *argv, **extra):
        """A dry run (whatever it says), then the rewrite of what it showed. `extra` is the
        rewrite's environment alone."""
        # The dry run's words are not read here, so it is asked for as `dry` asks for it:
        # one dry run of a given store, whoever wanted it.
        self.tool("slim", "--set", "keel", "--dry-run", *argv, *([] if "--json" in argv else ["--json"]))
        return self.tool("slim", "--set", "keel", "--approved", *argv, **extra)

    def again(self, *argv) -> dict:
        """The rewrite run once more after a stop, on the approval the dry run wrote before
        it: `slim --approved`, "run it again after a stop". No second dry run is owed, and
        one would only read the same snapshots a second time."""
        done = self.tool("slim", "--set", "keel", "--approved", "--json", *argv)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def reset(self) -> None:
        """The store, the home and the temp root as setUp left them, for a test that goes
        round more than once."""
        for top in (self.store, self.home, self.scratch):
            shutil.rmtree(top)
            top.mkdir()
        self.key.write_text("a scratch passphrase")

    def slim(self, *argv, **extra) -> dict:
        done = self.rewrite("--json", *argv, **extra)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def killed_at(self, step: str, *argv):
        """A rewrite stopped dead at a named step, through the tool's test seam, then an
        hour on: the locks it left name a dead pid, and the tool breaks them at that age."""
        done = self.rewrite(*argv, KEEL_BACKUP_SLIM_TEST="1", KEEL_BACKUP_SLIM_DIE_AT=step)
        self.assertEqual(done.returncode, -signal.SIGKILL, done.stdout + done.stderr)
        for lock in (".lock", ".slim-lock"):
            if os.path.lexists(self.home / lock):
                os.utime(self.home / lock, (1, 1), follow_symlinks=False)
        return done

    def changed_tool(self, old: str, new: str) -> Path:
        """A copy of the tool with one line of it changed, beside a link to the modules."""
        home = self.root / "changed"
        (home / "bin").mkdir(parents=True)
        os.symlink(ROOT / "keel", home / "keel")
        text = TOOL.read_text()
        self.assertEqual(text.count(old), 1)
        (home / "bin" / "keel-backup").write_text(text.replace(old, new))
        return home / "bin" / "keel-backup"

    def blob(self, sid: str) -> Path:
        return self.store / "sets" / "keel" / "snapshots" / sid[:4] / sid[4:6] / f"{sid}.tar.gz.gpg"

    def write_tree(self, where: Path, files: dict, dirs=()) -> None:
        for rel, data in files.items():
            path = where / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for rel in dirs:
            (where / rel).mkdir(parents=True, exist_ok=True)

    def old_tree(self, where: Path) -> None:
        self.write_tree(where, KEPT, KEPT_DIRS + DROPPED_DIRS)
        self.write_tree(where, {rel: data for rel, (_rule, data) in DROPPED.items()})
        shutil.copy(self.board, where / "state" / "board.db")

    def publish(self, sid: str, tree: Path) -> None:
        """One snapshot written straight into the store, as the tool packs one: every
        directory and file by name, tarred, gzipped, encrypted under the scratch key."""
        self.tree_is_standard = False           # a tree published by hand may have been edited
        names = sorted(str(p.relative_to(tree)) for p in tree.rglob("*"))
        listing = self.root / "names"
        listing.write_bytes(b"".join(os.fsencode(n) + b"\0" for n in names))
        blob = self.blob(sid)
        blob.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["bash", "-c", 'tar -cf - --null --no-recursion -T "$1" | gzip -9nc | ' + ENCRYPT,
             "_", str(listing), str(self.key), str(blob)],
            check=True, cwd=tree, capture_output=True)
        blob.chmod(0o600)

    def publish_members(self, sid: str, extra=()) -> None:
        """One snapshot written member by member: the old tree, then members a tree on this
        disk may not be able to hold (a name that differs only in case, a link, odd bytes).
        `extra` is (TarInfo, bytes or None) pairs."""
        tree = self.root / "old-tree"
        if not tree.exists():
            self.old_tree(tree)
        raw = self.root / "raw.tar"
        with tarfile.open(raw, "w", format=tarfile.PAX_FORMAT) as tar:
            for path in sorted(tree.rglob("*")):
                tar.add(path, arcname=str(path.relative_to(tree)), recursive=False)
            for info, data in extra:
                info.size = len(data) if data is not None else 0
                tar.addfile(info, io.BytesIO(data) if data is not None else None)
        blob = self.blob(sid)
        blob.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["bash", "-c", 'gzip -9nc "$1" | ' + ENCRYPT, "_", str(raw), str(self.key), str(blob)],
                       check=True, capture_output=True)
        blob.chmod(0o600)

    def left_as_it_was(self, sid: str, said: str) -> None:
        """A snapshot that cannot be read whole: the dry run says why and exits non-zero,
        it approves nothing for it, and the rewrite leaves the object that was there."""
        before = self.objects()[str(self.blob(sid).relative_to(self.store))]
        shown = self.tool("slim", "--set", "keel", "--dry-run")
        self.assertNotEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertIn(said, shown.stdout + shown.stderr)
        done = self.tool("slim", "--set", "keel", "--approved")
        self.assertIn("the dry run has not shown it", done.stdout + done.stderr)
        self.assertEqual(self.objects()[str(self.blob(sid).relative_to(self.store))], before)
        self.assertEqual(list(self.scratch.glob("keel-backup.*")), [], "its unpacked work is gone")

    def old_store(self, *ids) -> None:
        """The standard old tree published under each id. The archive of an id is made once
        in a process (`_BLOBS`) and copied after that, while the tree is still the standard
        one: a test that edits `old-tree` and publishes it does so itself, with `publish`."""
        tree = self.root / "old-tree"
        if not tree.exists():
            self.old_tree(tree)
            self.tree_is_standard = True
        for sid in ids or (OLD, NEW):
            if not self.tree_is_standard:
                self.publish(sid, tree)
                continue
            if sid not in _BLOBS:
                self.publish(sid, tree)
                self.tree_is_standard = True
                _BLOBS[sid] = self.blob(sid).read_bytes()
            blob = self.blob(sid)
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(_BLOBS[sid])
            blob.chmod(0o600)

    def unpack(self, sid: str) -> tuple[dict, set]:
        """({file: sha256}, {directory}) of one snapshot as the store holds it now."""
        where = Path(tempfile.mkdtemp(dir=self.root))
        subprocess.run(
            ["bash", "-c", 'set -o pipefail; gpg --batch --quiet --no-tty --pinentry-mode loopback '
             '--passphrase-file "$1" --decrypt "$2" | tar -xzf - -C "$3"',
             "_", str(self.key), str(self.blob(sid)), str(where)], check=True, capture_output=True)
        files ={str(p.relative_to(where)): sha(p.read_bytes()) for p in where.rglob("*") if p.is_file()}
        dirs = {str(p.relative_to(where)) for p in where.rglob("*") if p.is_dir()}
        return files, dirs

    def objects(self) -> dict:
        """{key: md5} of everything the store holds."""
        return {str(p.relative_to(self.store)): hashlib.md5(p.read_bytes()).hexdigest()
                for p in self.store.rglob("*") if p.is_file()}

    def snapshots(self) -> dict:
        """{key: md5} of the set's snapshots alone: what retention and status count."""
        return {k: v for k, v in self.objects().items() if k.startswith("sets/") and k.endswith(".tar.gz.gpg")}

    def kept_old(self) -> dict:
        """{id: md5} of the old archives a rewrite keeps under slim-old/."""
        return {Path(k).name[:-len(".tar.gz.gpg")]: v for k, v in self.objects().items()
                if k.startswith("slim-old/keel/")}

    def journal(self) -> dict:
        return json.loads((self.store / "sets" / "keel" / "slim.json").read_text())

    def assert_old(self, sid: str) -> None:
        files, _dirs = self.unpack(sid)
        self.assertEqual(set(files), set(KEPT) | set(DROPPED) | {"state/board.db"}, sid)

    def assert_slim(self, sid: str, also_kept=()) -> None:
        files, dirs = self.unpack(sid)
        want = {rel: sha(data) for rel, data in KEPT.items()}
        want["state/board.db"] = sha(self.board.read_bytes())
        for rel in also_kept:
            want[rel] = sha(DROPPED[rel][1])
        self.assertEqual(files, want, sid)
        for rel in KEPT_DIRS:
            self.assertIn(rel, dirs, "an empty directory the scan lists is kept")
        for rel in DROPPED_DIRS:
            self.assertNotIn(rel, dirs)


class MidReplace:
    """A store as a run stopped mid-replace leaves it, written by hand so it can be built on
    any store kind (the kill seam is a folder store's): the journal names a replace, the
    proven new archive sits under its temporary name, and the snapshot's own name holds
    whatever the test puts there."""

    def mid_replace(self, name_holds="old") -> dict:
        # The slimmed archive, and the digest of today's rules as a real replace journals it
        # (r2.F6), read off what a dry run of that very archive writes down. Both are made
        # once in a process (`_MID`), in a store of their own, and copied after that.
        if str(TOOL) not in _MID:
            slim_tree = self.root / "slim-tree"
            self.write_tree(slim_tree, KEPT, KEPT_DIRS)
            shutil.copy(self.board, slim_tree / "state" / "board.db")
            self.publish(OLD, slim_tree)
            self.dry()
            approved = self.home / "slim-approved.json"
            _MID[str(TOOL)] = (self.blob(OLD).read_bytes(),
                               json.loads(approved.read_text())["sets"]["keel"][OLD]["rules_digest"])
            self.reset()
        slimmed, today = _MID[str(TOOL)]
        tmp = self.store / "slim-tmp" / "keel" / f"{OLD}.new"
        tmp.parent.mkdir(parents=True)
        tmp.write_bytes(slimmed)
        tmp.chmod(0o600)
        entry = {"id": OLD, "key": str(self.blob(OLD).relative_to(self.store)), "rules_digest": today,
                 "md5": hashlib.md5(tmp.read_bytes()).hexdigest(), "was_md5": "0" * 32,
                 "bytes": tmp.stat().st_size, "was_bytes": 1, "at": "2026-10-01T00:00:00Z"}
        if name_holds == "old":
            self.old_store(OLD)
            entry["was_md5"] = hashlib.md5(self.blob(OLD).read_bytes()).hexdigest()
        elif name_holds == "half":
            self.blob(OLD).parent.mkdir(parents=True, exist_ok=True)
            self.blob(OLD).write_bytes(tmp.read_bytes()[:500])
        journal = self.store / "sets" / "keel" / "slim.json"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({"set": "keel", "done": {}, "replacing": entry}))
        return entry

    def stub_rclone(self, fail_when: str) -> str:
        """A PATH whose rclone fails any call whose arguments match, and is rclone otherwise."""
        bin_dir = self.root / "stub-bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "rclone"
        stub.write_text('#!/bin/bash\ncase "$*" in ' + fail_when +
                        ') echo "Failed: the store did not answer" >&2; exit 1 ;; esac\n'
                        f'exec "{RCLONE}" "$@"\n')
        stub.chmod(0o755)
        return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def member(name: str, mode=0o644, kind=tarfile.REGTYPE, link="") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode, info.type, info.linkname, info.mtime = mode, kind, link, 1_700_000_000
    return info


def find_of(name: str) -> str:
    """One function of the tool, as written."""
    text = TOOL.read_text()
    start = text.index(f"\n{name}() {{")
    return text[start:text.index("\n}\n", start)]
