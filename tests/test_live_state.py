"""The live board is the live checkout's, and a worktree gets its own.

WHAT HAPPENED ON 2026-09-20. `keel.toml` is tracked and says `state_dir = "~/keel/state"`,
an absolute-by-home path to the LIVE checkout's state rather than a path relative to the
checkout the file sits in. Every house builds in a git worktree under
`<live>/state/worktrees/<card>/`, and that worktree carries the same `keel.toml`. So code
run from a worktree that loaded the worktree's own config resolved `state_dir` to the LIVE
board and wrote to it. Five separate times that day: four houses ran a scratch voice
gateway from their worktree for a live-socket check and their spoken test captures were
filed as real cards on the live board ("a thought" six times, "remember the bearing export"
nine times), and the test fence found the same mechanism from the other side, where
`bin/kb help` run from a worktree opened the live board.

THE RULE THESE TESTS HOLD. A config whose `state_dir` resolves outside the checkout that
loaded it is not handed out pointing at that other checkout's board. It is redirected to
this checkout's own `state/`, which is a scratch board, unless the caller said otherwise:
`KEEL_CONFIG` (or a path argument) names a toml on purpose, and `KEEL_LIVE_STATE=1` is the
explicit opt-in. The live checkout resolves exactly as it always has, on either machine.

WHAT THE FIRST VERSION OF THE RULE MISSED, later the same day. It compared `state_dir`
against `KEEL_HOME`, and a house's environment carries `KEEL_HOME=<the live checkout>`. So
code running from a WORKTREE, with the live checkout named in its environment, compared the
live `state_dir` against the live root, found it inside, and opened his board: 84 fake cards
from `bin/keel-voice-selftest`, whose capture checks speak two phrases and expect cards
back. The comparison is now against the checkout the RUNNING PACKAGE lives in as well, which
no environment variable can move, and `BorrowedHomeTest` below is that shape.
"""

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from keel import config as config_module

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "bin" / "kb"
SELFTEST = ROOT / "bin" / "keel-voice-selftest"

# The shipped file's shape, reduced to what this is about: the two absolute-by-home paths.
TOML = """\
[keel]
state_dir = "~/keel/state"
segments_dir = "~/keel/segments"
fetch_lock_dir = "~/keel/state/fetch-locks"
drain_paused = false
[spaces.personal]
config_dir = "~/nowhere"
"""


class LayoutCase(unittest.TestCase):
    """A throwaway HOME holding a live checkout and one house's worktree under it.

    Faithful to the trap rather than a stand-in for it: HOME really moves, the toml really
    says `~/keel/state`, and the worktree really sits at `<live>/state/worktrees/<card>/`.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Resolved, because `repo_root` resolves: on a Mac the temp directory is reached
        # through `/var`, which is a symlink to `/private/var`, and the two spellings of
        # one directory would read as two checkouts.
        self.home = Path(self.tmp.name).resolve()
        self.live = self.home / "keel"
        self.worktree = self.live / "state" / "worktrees" / "c-999"
        self.worktree.mkdir(parents=True)
        (self.live / "state").mkdir(exist_ok=True)
        (self.live / "keel.toml").write_text(TOML)
        (self.worktree / "keel.toml").write_text(TOML)
        self.env("HOME", str(self.home))

    def env(self, key: str, value: str | None) -> None:
        """Set or drop one variable for this test only."""
        before = os.environ.get(key)
        self.addCleanup(lambda: os.environ.__setitem__(key, before) if before is not None
                        else os.environ.pop(key, None))
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def load_from(self, root: Path, **extra):
        """`config.load()` as a process whose code root is `root` would reach it."""
        self.env("KEEL_HOME", str(root))
        for key, value in extra.items():
            self.env(key, value)
        return config_module.load(ensure=False)

    def child_env(self, root: Path, **extra) -> dict:
        env = {key: value for key, value in os.environ.items() if not key.startswith("KEEL_")}
        env.update(HOME=str(self.home), KEEL_HOME=str(root), **extra)
        return env

    def plant(self, checkout: Path) -> Path:
        """Give `checkout` code of its own: the `keel` package and the `bin/kb` that runs it.

        Copied rather than symlinked, because the whole question is which checkout the
        running package lives in and a symlink resolves back to this one. `bin/kb` puts its
        own parent's parent first on `sys.path`, so the copy is what a `kb` started there
        imports.
        """
        shutil.copytree(ROOT / "keel", checkout / "keel",
                        ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
        (checkout / "bin").mkdir(exist_ok=True)
        shutil.copy2(KB, checkout / "bin" / "kb")
        return checkout


class WorktreeTest(LayoutCase):
    def test_a_worktree_does_not_resolve_to_the_live_state(self):
        cfg = self.load_from(self.worktree)
        self.assertNotEqual(cfg.state_dir, self.live / "state")
        self.assertEqual(cfg.state_dir, self.worktree / "state")
        self.assertEqual(cfg.segments_dir, self.worktree / "segments")
        self.assertEqual(cfg.fetch_locks, self.worktree / "state" / "fetch-locks")

    def test_it_says_it_is_scratch_and_names_the_board_it_did_not_open(self):
        cfg = self.load_from(self.worktree)
        self.assertTrue(cfg.scratch)
        self.assertEqual(cfg.wanted_state, self.live / "state")
        self.assertIn("scratch", cfg.scratch_note)
        self.assertIn(str(self.live / "bin" / "kb"), cfg.scratch_note)

    def test_a_board_url_is_ignored_with_a_note_on_every_checkout(self):
        """c-622: `board_url` made a machine a client of another's board over HTTP. Keel
        runs on one machine now, so an old config that still names one opens its own board
        and says the key is ignored, rather than failing to load."""
        body = TOML.replace("[keel]\n", '[keel]\nboard_url = "https://keel.example"\n')
        (self.worktree / "keel.toml").write_text(body)
        (self.live / "keel.toml").write_text(body)
        for checkout in (self.worktree, self.live):
            cfg = self.load_from(checkout)
            self.assertFalse(hasattr(cfg, "board_url"), "nothing carries the key (c-648)")
            self.assertIn("[keel] board_url: Shipyard runs on one machine now (c-622), so it is ignored",
                          cfg.warnings)

    def test_a_scratch_config_does_not_keep_the_live_deck_s_port(self):
        """E4 (c-415): a scratch `keel serve` on 8790 is the live deck's port, so the scratch
        gets a port of its own, the same one every time for the same checkout."""
        body = TOML.replace("[keel]\n", "[keel]\nserve_port = 8790\n")
        (self.worktree / "keel.toml").write_text(body)
        (self.live / "keel.toml").write_text(body)
        scratch = self.load_from(self.worktree)
        self.assertNotEqual(scratch.serve_port, 8790)
        self.assertEqual(scratch.serve_port, self.load_from(self.worktree).serve_port)
        self.assertEqual(scratch.live_serve_port, 8790)
        self.assertEqual(self.load_from(self.live).serve_port, 8790)

    def test_a_scratch_config_does_not_read_or_mint_the_shared_house_key(self):
        """The shared key lives under the HOME, not under state, so moving state_dir did
        not move it: a scratch process could call the peer's door with a real credential."""
        from keel import board as board_module, housetier
        live = self.load_from(self.live)
        live_home = dataclasses.replace(live, home=self.home)
        housetier.mint_shared(live_home)
        self.assertTrue(housetier.shared_key(live_home))
        scratch = dataclasses.replace(self.load_from(self.worktree), home=self.home)
        self.assertEqual(housetier.shared_key(scratch), "")
        with self.assertRaises(board_module.Refused):
            housetier.mint_shared(scratch, force=True)

    def test_a_scratch_serve_refuses_the_live_port_even_when_named(self):
        """`keel serve --port 8790` from a worktree is refused, whatever the toml says."""
        scratch = self.load_from(self.worktree)
        with self.assertRaises(config_module.ConfigError):
            config_module.guard_port(scratch, scratch.live_serve_port)
        config_module.guard_port(scratch, scratch.serve_port)          # its own is fine
        config_module.guard_port(self.load_from(self.live), 8790)      # the live deck's own

    def test_the_live_checkout_resolves_exactly_as_before(self):
        cfg = self.load_from(self.live)
        self.assertFalse(cfg.scratch)
        self.assertEqual(cfg.state_dir, self.live / "state")
        self.assertEqual(cfg.segments_dir, self.live / "segments")
        self.assertEqual(cfg.db_path, self.live / "state" / "board.db")

    def test_the_opt_in_hands_the_live_state_to_a_worktree(self):
        cfg = self.load_from(self.worktree, KEEL_LIVE_STATE="1")
        self.assertFalse(cfg.scratch)
        self.assertEqual(cfg.state_dir, self.live / "state")
        self.assertEqual(cfg.segments_dir, self.live / "segments")

    def test_a_named_toml_is_taken_at_its_word(self):
        """`KEEL_CONFIG`, and the path argument that is its in-process twin. Naming a toml
        is deliberate, so it resolves as written: this is what the scratch deck recipe in
        `<install>/history/tests/live_deck.md` and every test helper rely on."""
        self.env("KEEL_HOME", str(self.worktree))
        self.env("KEEL_CONFIG", str(self.worktree / "keel.toml"))
        self.assertEqual(config_module.load(ensure=False).state_dir, self.live / "state")
        self.env("KEEL_CONFIG", None)
        by_path = config_module.load(self.worktree / "keel.toml", ensure=False)
        self.assertEqual(by_path.state_dir, self.live / "state")


class BorrowedHomeTest(LayoutCase):
    """`KEEL_HOME` names the live checkout, and the code that is running is a worktree's.

    THE SHAPE THAT BEAT THE FIRST GUARD, and the one a house is always in: the drain hands
    every house `KEEL_HOME=<the live checkout>`, so comparing `state_dir` against that name
    found the live state inside the live root and called it this checkout's own. The code
    doing the comparing was the worktree's. Both checkouts here carry real code, because the
    comparison is now against the package's own directory and nothing else can stand in for
    it.
    """

    def setUp(self):
        super().setUp()
        self.plant(self.live)
        self.plant(self.worktree)

    def kb(self, checkout: Path, *argv: str, **extra) -> subprocess.CompletedProcess:
        """`<checkout>/bin/kb`, which imports `<checkout>`'s own `keel` package."""
        home = extra.pop("home", self.live)
        return subprocess.run([sys.executable, str(checkout / "bin" / "kb"), *argv],
                              capture_output=True, text=True, timeout=60,
                              env=self.child_env(home, **extra))

    def create(self, checkout: Path, **extra) -> subprocess.CompletedProcess:
        return self.kb(checkout, "--actor", "voice", "create", "--space", "personal",
                       "--title", "a thought", "--json", **extra)

    def test_a_worktrees_kb_files_on_the_worktrees_own_board(self):
        """`python3 <worktree>/bin/kb create` with `KEEL_HOME=<live>`: that kb's package is
        the worktree's, so the board is the worktree's."""
        done = self.create(self.worktree)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["id"])
        self.assertFalse((self.live / "state" / "board.db").exists(),
                         "a card from a worktree reached the live board")
        self.assertTrue((self.worktree / "state" / "board.db").exists())

    def test_an_inherited_keel_url_takes_no_kb_to_another_board(self):
        """Review finding 8, and c-622: `KEEL_URL` in the environment (every Mac house had
        it) once made kb a client of another machine's board. Nothing reads it now: each
        checkout's kb files on its own board."""
        done = self.create(self.worktree, KEEL_URL="http://127.0.0.1:9")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.worktree / "state" / "board.db").exists())
        done = self.create(self.live, KEEL_URL="http://127.0.0.1:9", home=self.live)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.live / "state" / "board.db").exists())


    def test_the_live_checkouts_own_kb_by_absolute_path_is_still_the_live_board(self):
        """The house contract's one route to the live board: the live checkout's `kb`, whose
        package IS the live checkout's. Unchanged."""
        done = self.create(self.live)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.live / "state" / "board.db").exists())
        self.assertNotIn("scratch", done.stderr)


    def test_a_keel_home_that_is_no_checkout_is_still_honoured(self):
        """A scratch `KEEL_HOME` with a toml of its own and no code in it: nobody else owns
        that state, so it is opened as written. This is how a test config and the scratch
        deck recipe run, and it is what keeps the redirect from pointing them here."""
        scratch = self.home / "scratch"
        scratch.mkdir()
        (scratch / "keel.toml").write_text(TOML.replace("~/keel/state", "state")
                                           .replace("~/keel/segments", "segments")
                                           .replace("~/keel/state/fetch-locks", "fetch-locks"))
        done = self.create(self.live, home=scratch)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((scratch / "state" / "board.db").exists())
        self.assertFalse((self.live / "state" / "board.db").exists())


class PredicateTest(LayoutCase):
    """The comparison itself, with the package named rather than inferred.

    `borrows_state` reads the running package's own directory when it is not told one, which
    in this process is this checkout. Naming it is how the four cases are stated side by
    side, and the subprocess tests above are the same four through the real boundary.
    """

    def test_the_state_is_the_running_packages_own(self):
        self.assertFalse(config_module.borrows_state(self.live, self.live / "state",
                                                     package=self.live))

    def test_a_worktrees_package_does_not_own_the_live_state(self):
        """The root here is a checkout with code of its own, which is what makes the state
        it names somebody else's rather than a scratch directory's."""
        self.plant(self.live)
        self.assertTrue(config_module.borrows_state(self.live, self.live / "state",
                                                    package=self.worktree))

    def test_a_root_with_no_code_in_it_owns_what_it_names(self):
        scratch = self.home / "scratch"
        scratch.mkdir()
        self.assertFalse(config_module.borrows_state(scratch, scratch / "state",
                                                     package=self.live))

    def test_the_state_another_checkout_hangs_off_is_borrowed(self):
        self.plant(self.live)
        self.assertTrue(config_module.borrows_state(self.worktree, self.live / "state",
                                                    package=self.worktree))

    def test_the_scratch_goes_where_the_refused_state_is_not(self):
        """The root it was pointed at, unless that root's own `state/` is the board being
        kept away from, in which case it is the checkout the code lives in."""
        self.assertEqual(config_module.scratch_root(self.live, self.live / "state",
                                                    package=self.worktree), self.worktree)
        self.assertEqual(config_module.scratch_root(self.worktree, self.live / "state",
                                                    package=self.worktree), self.worktree)
        scratch = self.home / "scratch"
        self.assertEqual(config_module.scratch_root(scratch, self.live / "state",
                                                    package=self.live), scratch)


class VoiceSelftestFenceTest(LayoutCase):
    """`bin/keel-voice-selftest` under a house's environment, which is how it always ran.

    ITS CAPTURE CHECKS SPEAK AND EXPECT A CARD BACK, and with `KEEL_HOME` naming the live
    checkout the card was a real one: 84 of them on 2026-09-20, "a thought" and "remember the
    bearing export", filed by houses proving their work. The selftest now builds a scratch
    world before it imports `harbor_voice` and files through a `kb` stand-in of its own.
    `--fence-report` runs that prologue, files one capture through it and prints what it
    decided, stopping before the selftest's own imports so this runs under the stdlib
    interpreter rather than `.venv-voice`.
    """

    def setUp(self):
        super().setUp()
        (self.live / "bin").mkdir(exist_ok=True)
        self.board = self.live / "live-board.jsonl"
        kb = self.live / "bin" / "kb"
        kb.write_text("#!/usr/bin/env python3\n"
                      "import json, sys\n"
                      f"open({str(self.board)!r}, 'a').write(json.dumps(sys.argv[1:]) + chr(10))\n"
                      "print(json.dumps({'id': 'c-901'}) if 'create' in sys.argv else '[]')\n")
        kb.chmod(0o755)

    def report(self, **extra) -> dict:
        """The selftest's fence, run as a house would have run the whole thing."""
        env = self.child_env(self.live, KEEL_HOST="mac", KEEL_CARD="c-999", **extra)
        done = subprocess.run([sys.executable, str(SELFTEST), "--fence-report"],
                              capture_output=True, text=True, timeout=300, env=env)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout.splitlines()[-1])

    def test_no_capture_reaches_the_live_board(self):
        self.report()
        self.assertFalse(self.board.exists(),
                         f"the selftest filed on the live board: "
                         f"{self.board.read_text() if self.board.exists() else ''}")

    def test_the_capture_lands_on_the_stand_in_inside_the_scratch(self):
        found = self.report()
        scratch = Path(found["scratch"])
        self.assertEqual(found["kb"], str(scratch / "bin" / "kb"))
        self.assertTrue(Path(found["data"]).is_relative_to(scratch), found["data"])
        self.assertTrue(found["card"]["id"], found["card"])
        asked = [call["argv"] for call in found["kb_calls"]]
        self.assertTrue(any("create" in argv for argv in asked), asked)

    def test_every_keel_variable_the_house_had_is_dropped(self):
        found = self.report(KEEL_TOKEN="a-real-token")
        kept = found["keel_env"]
        self.assertNotIn("KEEL_CARD", kept)
        self.assertNotIn("KEEL_HOST", kept)
        self.assertNotIn("KEEL_TOKEN", kept)
        self.assertEqual(kept["KEEL_HOME"], found["scratch"])

    def test_the_home_directory_moves_too(self):
        """`~` is half the trap: `keel.toml` says `state_dir = "~/keel/state"`, so a child
        that falls back to the toml lands on the live state however the `KEEL_*` names were
        handled."""
        found = self.report()
        self.assertTrue(Path(found["home"]).is_relative_to(Path(found["scratch"])),
                        found["home"])


class MissingTomlTest(LayoutCase):
    def test_a_keel_home_with_no_toml_says_so(self):
        """It used to be a bare `FileNotFoundError` traceback out of `load`, which reads
        like a bug in Keel rather than a scratch directory that is missing its file."""
        empty = self.home / "scratch"
        empty.mkdir()
        with self.assertRaises(config_module.ConfigError) as caught:
            self.load_from(empty)
        message = str(caught.exception)
        self.assertIn(str(empty / "etc" / "shipyard.example.toml"), message)
        self.assertIn("KEEL_HOME", message)


    def test_kb_prints_the_reason_instead_of_a_traceback(self):
        empty = self.home / "scratch"
        empty.mkdir()
        done = subprocess.run([sys.executable, str(KB), "list"], capture_output=True,
                              text=True, timeout=60, env=self.child_env(empty))
        self.assertEqual(done.returncode, 1)
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("no config of its own", done.stderr)


class SubprocessKbTest(LayoutCase):
    """The whole point, through the real boundary: `kb` started from a worktree.

    This is the shape the fence caught (`bin/kb` with no `KEEL_CONFIG`) and the shape a
    scratch voice gateway reaches the board through (`harbor_voice/snapshot.py` runs
    `$KEEL_HOME/bin/kb` with `KEEL_HOME` passed explicitly).
    """

    def kb(self, root: Path, *argv: str, **extra) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(KB), *argv], capture_output=True,
                              text=True, timeout=60, env=self.child_env(root, **extra))


    def test_it_says_on_the_way_past_which_board_it_opened(self):
        done = self.kb(self.worktree, "list", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("scratch", done.stderr)
        self.assertIn(str(self.live / "bin" / "kb"), done.stderr)


class ChildEnvTest(unittest.TestCase):
    """A scratch config hands no `KEEL_CONFIG` down.

    `keel/house.py` and `keel/actions.py` pass the toml they loaded to every `kb` they
    start, and a named toml is taken at its word, so passing a worktree's own file would
    send the child to the live board the redirect had just refused. Both pass `KEEL_HOME`
    instead, which gets the child to the same answer by the same rule.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from tests.helpers import make_config
        self.cfg = make_config(Path(self.tmp.name))

    def both(self, cfg) -> list[dict]:
        from keel import actions, house
        return [house.house_env(cfg, "c-1"), actions.kb_env(cfg)]

    def test_a_named_toml_still_reaches_the_child(self):
        cfg = dataclasses.replace(self.cfg, source=ROOT / "keel.toml")
        for env in self.both(cfg):
            self.assertEqual(env["KEEL_CONFIG"], str(ROOT / "keel.toml"))

    def test_a_scratch_config_sends_the_root_and_not_the_toml(self):
        cfg = dataclasses.replace(self.cfg, source=ROOT / "keel.toml", scratch=True,
                                  wanted_state=Path("/nowhere/state"))
        for env in self.both(cfg):
            self.assertNotIn("KEEL_CONFIG", env)
            self.assertEqual(env["KEEL_HOME"], str(cfg.root))


class VoicePackageTest(LayoutCase):
    """`voice/harbor_voice/config.py` finds Keel by itself and cannot import `keel`.

    It runs from its own interpreter (`.venv-voice`), so the rule is written twice on
    purpose. What a stdlib test can hold is the whole of the lookup: the module is plain
    standard library, so it imports under this interpreter, and every value it decides is
    read at import time from the environment. What it cannot hold is a running gateway;
    `bin/keel-voice-selftest` holds the startup line that reports the answer.
    """

    def setUp(self):
        super().setUp()
        for checkout in (self.live, self.worktree):
            package = checkout / "voice" / "harbor_voice"
            package.mkdir(parents=True)
            for name in ("__init__.py", "config.py"):
                (package / name).write_text((ROOT / "voice" / "harbor_voice" / name).read_text())
            (checkout / "bin").mkdir(exist_ok=True)
            (checkout / "bin" / "kb").write_text("#!/bin/sh\nexit 0\n")

    def values(self, checkout: Path, **extra) -> dict:
        """What `harbor_voice.config` resolves, from a process whose package is `checkout`'s."""
        env = {key: value for key, value in os.environ.items() if not key.startswith("KEEL_")}
        env.update(HOME=str(self.home), PYTHONPATH=str(checkout / "voice"), **extra)
        done = subprocess.run(
            [sys.executable, "-c",
             "import json; from harbor_voice import config; "
             "print(json.dumps({'home': str(config.KEEL_HOME), 'state': str(config.STATE), "
             "'data': str(config.DATA), 'kb': str(config.KB), 'board': config.board_kind()}))"],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_with_no_keel_home_it_follows_its_own_checkout_not_the_home_directory(self):
        """It defaulted to `~/keel`, so a gateway started from a worktree with no
        `KEEL_HOME` wrote its transcript, its filler cache, its judge log and its
        recordings into the LIVE `state/voice/`."""
        found = self.values(self.worktree)
        self.assertEqual(found["home"], str(self.worktree))
        self.assertEqual(found["state"], str(self.worktree / "state"))
        self.assertEqual(found["data"], str(self.worktree / "state" / "voice"))
        self.assertEqual(found["kb"], str(self.worktree / "bin" / "kb"))

    def test_it_names_the_board_it_will_write_to(self):
        self.assertEqual(self.values(self.worktree)["board"], "scratch")
        self.assertEqual(self.values(self.live)["board"], "live")

    def test_a_keel_home_naming_another_checkout_does_not_move_the_state(self):
        """The house's environment, verbatim: `KEEL_HOME=<the live checkout>` while the
        package on `PYTHONPATH` is the worktree's. Every writable path stays in the worktree
        and the `kb` it would call is the worktree's own, which is a scratch board."""
        found = self.values(self.worktree, KEEL_HOME=str(self.live))
        self.assertEqual(found["home"], str(self.worktree))
        self.assertEqual(found["data"], str(self.worktree / "state" / "voice"))
        self.assertEqual(found["kb"], str(self.worktree / "bin" / "kb"))
        self.assertEqual(found["board"], "scratch")


    def test_the_live_gateway_reads_its_own_home_as_it_always_did(self):
        found = self.values(self.live, KEEL_HOME=str(self.live))
        self.assertEqual(found["home"], str(self.live))
        self.assertEqual(found["data"], str(self.live / "state" / "voice"))
        self.assertEqual(found["board"], "live")

    def test_a_worktrees_gateway_pointed_at_the_live_kb_reads_live(self):
        """The verbatim launch of 2026-09-20: a scratch `KEEL_HOME` whose `bin/kb` is the
        live checkout's. The board is whatever that `kb` opens, so the word is `live` and
        the gateway refuses it (`harbor_voice/server.py`) rather than filing captures on
        his board while its log says nothing."""
        scratch = self.home / "scratch"
        (scratch / "bin").mkdir(parents=True)
        (scratch / "bin" / "kb").symlink_to(self.live / "bin" / "kb")
        self.assertEqual(self.values(self.worktree, KEEL_HOME=str(scratch))["board"], "live")


if __name__ == "__main__":
    unittest.main()
