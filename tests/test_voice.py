"""`keel voice`: the plist and its environment, the interpreter search and the venv
version probe against fake interpreters, install without loading, and status lines. Plus
the two pieces of the gateway that are pure standard library, the end-of-utterance state
machine and the corpus recorder's housekeeping.

THE GATEWAY PACKAGE IS STILL NOT IMPORTED WHOLESALE, and the rule it was written under
still holds: its speech engines live in their own venv and importing them here would make
`make test` depend on a machine learning tree. `vad.Endpointer` and `record` are the
exception because they import NOTHING outside the standard library. The endpointer is a
timer over booleans (sherpa is the separate `SileroVAD` class, which this never touches)
and the recorder is `wave` and `pathlib`. They are also exactly the code a bad number
would hide in, and the hangover decides when he gets cut off mid-sentence, so testing
them in the venv's selftest alone would leave the arithmetic unchecked by `make test`.

`speech` IS THE THIRD, ADDED FOR THE SAME REASON (c-316). Its module body is standard
library too: every engine's heavyweight import (`kokoro`, onnxruntime, parakeet) is inside
that engine's own `__init__`, so importing the module builds nothing. What is tested here
is `SayTTS`'s probe of `say -v ?`, and it is tested HERE rather than in the venv's selftest
because the selftest runs on this box, where there is no `say` at all: a probe that only
ever ran on Linux would be a probe nothing had exercised. `subprocess.run` is faked, so
nothing is executed either way."""

import io
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from keel import service, voice
from keel.config import Config
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "voice"))
from harbor_voice import config as vconfig                              # noqa: E402
from harbor_voice import record as vrecord                              # noqa: E402
from harbor_voice import speech as vspeech                              # noqa: E402
from harbor_voice import vad as vvad                                    # noqa: E402

UP = {"ok": True, "upSeconds": 42.0, "lookupTier": "removed",
      "stt": {"backend": "parakeet-mlx", "ready": True, "why": ""}, "tts": {"backend": "google"},
      "vad": {"backend": "silero", "ready": True, "why": "", "hangoverSeconds": 2.5,
              "minSpeechSeconds": 0.3},
      "record": {"recording": False, "count": 0, "megabytes": 0.0, "oldestDays": 0.0},
      "snapshot": {"healthy": True, "ageSeconds": 1.0, "error": ""}}


# 32 ms, the window Silero insists on and the frame the socket feeds the endpointer.
FRAME = 0.032


def _run(endpointer, pattern: str) -> float | None:
    """Drive the endpointer with a string: `.` is speech, ` ` is silence.

    Returns when it fired, in seconds, or None. A readable way to write the only thing
    that actually matters about this class, which is WHEN it says he has stopped.
    """
    for i, ch in enumerate(pattern):
        if endpointer.feed(ch == ".", FRAME):
            return (i + 1) * FRAME
    return None


def fake_python(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class VoiceCase(unittest.TestCase):
    def install_unit(self, *credentials: str) -> None:
        """Stand in for what `keel voice install --load` leaves on the machine: a unit that
        carries a `LoadCredential=` per key. `key_set` reads the INSTALLED copy rather than
        the one this checkout would render, so a worktree cannot make it restart a live
        gateway for a credential that gateway has never heard of (c-313)."""
        directory = self.paths.manager.installed_dir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{voice.LABEL}.service").write_text(
            "".join(f"LoadCredential={name}:/somewhere/{name}\n" for name in credentials))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg: Config = make_config(self.dir)
        self.cfg.root = self.dir / "keel"
        (self.cfg.root / "etc").mkdir(parents=True)
        (self.cfg.root / "bin").mkdir()
        self.cfg.voice_port = 4391
        pin = mock.patch.object(service, "platform", return_value=service.LAUNCHD)
        pin.start()
        self.addCleanup(pin.stop)
        self.home = self.dir / "home"
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        # THE LOADED COPY GOES IN THIS TMPDIR, NEVER IN THE REAL `~/Library/LaunchAgents`.
        # a `--load` copies a plist into the manager's directory for real, and against the
        # process's own home that overwrote the LIVE `dev.keel.voice.plist` with the
        # test's fixture on every `make test` run.
        self.paths = voice.Paths(root=self.cfg.root, state_dir=self.cfg.state_dir,
                                 home=self.home)


class PlistTest(VoiceCase):
    def test_renders_the_venv_python_running_the_gateway_from_the_repo(self):
        plist = plistlib.loads(voice.render_plist(self.cfg, self.paths, home=Path("/Users/me"), python="/v/bin/python"))
        self.assertEqual(plist["Label"], "dev.keel.voice")
        self.assertEqual(plist["ProgramArguments"], ["/v/bin/python", str(self.cfg.root / "bin" / "keel-voice-gateway")])
        self.assertEqual(plist["WorkingDirectory"], str(self.cfg.root))
        self.assertTrue(plist["KeepAlive"] and plist["RunAtLoad"])
        self.assertEqual(plist["StandardOutPath"], str(self.cfg.state_dir / "logs" / "voice.log"))
        self.assertEqual(plist["StandardErrorPath"], plist["StandardOutPath"])

    def test_environment_carries_the_voice_table_and_the_paths_and_never_a_config_dir(self):
        env = plistlib.loads(voice.render_plist(self.cfg, self.paths, home=Path("/Users/me"), python="p"))["EnvironmentVariables"]
        self.assertEqual(env["KEEL_HOME"], str(self.cfg.root))
        self.assertEqual(env["KEEL_SEGMENTS_DIR"], str(self.cfg.segments_dir))
        # The deck's port, for the digest: the gateway reads /api/state on loopback, and a
        # default that disagreed with keel.toml would cost every turn its provider rows.
        self.assertEqual(env["KEEL_SERVE_PORT"], str(self.cfg.serve_port))
        self.assertEqual(env["HARBOR_VOICE_PORT"], "4391")
        self.assertEqual(env["HARBOR_VOICE_SPACE_DEFAULT"], "personal")
        self.assertEqual(env["HARBOR_VOICE_MODE_DEFAULT"], "capture")
        self.assertEqual(env["HARBOR_VOICE_ENGINE_DEFAULT"], "google")
        self.assertEqual(env["HOME"], "/Users/me")
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertEqual(env["PATH"].split(":")[:3], [str(self.cfg.root / "bin"), "/Users/me/.local/bin", "/opt/homebrew/bin"])
        self.assertEqual(env["KEEL_ADAPTERS_DIR"], str(self.cfg.adapters_dir))
        # The Mac keeps the gateway's own speech defaults (MLX in, Google then kokoro out).
        self.assertNotIn("HARBOR_VOICE_STT", env)
        self.assertNotIn("HARBOR_VOICE_TTS", env)

    def test_the_page_s_three_defaults_all_come_out_of_the_voice_table(self):
        """One source, two readers (V7). The page is static files that cannot read
        keel.toml, so the gateway serves these in /voice/flags.js and the service file is
        how the gateway learns them. A value that stopped travelling this way would be a
        control whose default silently reverted to the package's own."""
        self.cfg.voice_mode_default = "talk"
        self.cfg.voice_space_default = "work"
        self.cfg.voice_engine_default = "kokoro"
        env = voice.environment(self.cfg, self.paths, home=Path("/Users/me"))
        self.assertEqual(env["HARBOR_VOICE_MODE_DEFAULT"], "talk")
        self.assertEqual(env["HARBOR_VOICE_SPACE_DEFAULT"], "work")
        self.assertEqual(env["HARBOR_VOICE_ENGINE_DEFAULT"], "kokoro")

    def test_the_venv_python_is_picked_up_when_it_exists(self):
        venv_py = self.paths.venv_python
        venv_py.parent.mkdir(parents=True)
        venv_py.write_text("")
        plist = plistlib.loads(voice.render_plist(self.cfg, self.paths, home=Path("/Users/me")))
        self.assertEqual(plist["ProgramArguments"][0], str(venv_py))

    def test_install_writes_the_plist_and_the_state_dirs_without_touching_launchd(self):
        out = io.StringIO()
        with mock.patch.object(voice.subprocess, "run") as run, redirect_stdout(out):
            code = voice.install(self.cfg, self.paths, load=False)
        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertTrue((self.paths.etc / "dev.keel.voice.plist").is_file())
        self.assertTrue((self.paths.data / "cache").is_dir())
        self.assertTrue(self.paths.log.parent.is_dir())
        self.assertIn("not loaded", out.getvalue())
        self.assertIn("no .venv-voice", out.getvalue())


class UnitTest(VoiceCase):
    def test_the_systemd_unit_outweighs_the_engine_for_the_cpu(self):
        """Nice orders processes only inside one cgroup, and on Linux the houses live in
        the engine's unit: the gateway's CPUWeight is what puts a spoken turn ahead."""
        text = service.unit(voice.service(self.cfg, self.paths, python="/v/bin/python"))
        self.assertIn(f"CPUWeight={voice.VOICE_CPU_WEIGHT}", text)
        self.assertGreater(voice.VOICE_CPU_WEIGHT, 100)
        self.assertIn(f"ExecStart=/v/bin/python {self.paths.gateway}", text)
        self.assertIn("Restart=always", text)
        self.assertIn(f"StandardOutput=append:{self.paths.log}", text)

    def test_the_box_hears_with_sherpa_and_falls_back_to_kokoro_onnx(self):
        """On Linux the unit names the ONNX pair: the Mac's engines are Apple-silicon
        builds, and `say` does not exist there (c-286)."""
        with mock.patch.object(service, "platform", return_value=service.SYSTEMD):
            text = service.unit(voice.service(self.cfg, self.paths, python="/v/bin/python"))
        self.assertIn("HARBOR_VOICE_STT=sherpa", text)
        self.assertIn("HARBOR_VOICE_TTS=google,kokoro-onnx,browser", text)
        self.assertNotIn("say", voice.LINUX_SPEECH["HARBOR_VOICE_TTS"].split(","))

    def test_uninstall_stops_it_and_keeps_the_checkouts_copy(self):
        installed = self.paths.manager.installed_dir / "dev.keel.voice.plist"
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(service.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
             redirect_stdout(io.StringIO()):
            voice.install(self.cfg, self.paths, load=True)
            self.assertTrue(installed.is_file())
            self.assertEqual(voice.uninstall(self.cfg, self.paths), 0)
        self.assertFalse(installed.exists())
        self.assertTrue((self.paths.etc / "dev.keel.voice.plist").is_file())


class WhichConfigTest(VoiceCase):
    """c-711: the gateway and every `kb` and `keel` it runs read the config the service was
    installed from, by the rule a house's hooks are handed theirs (`config.named_toml`)."""

    def env(self) -> dict:
        return plistlib.loads(voice.render_plist(self.cfg, self.paths, home=self.home,
                                                 python="p"))["EnvironmentVariables"]

    def test_the_service_names_the_config_of_an_install(self):
        real = os.path.realpath(self.dir)       # written out below, so no link may be in it
        os.mkdir(f"{real}/install")
        self.cfg.source = Path(f"{real}/install/config.toml")
        self.assertEqual(self.env()["KEEL_CONFIG"], f"{real}/install/config.toml")
        with mock.patch.object(service, "platform", return_value=service.SYSTEMD):
            unit = service.unit(voice.service(self.cfg, self.paths, python="/v/bin/python"))
        self.assertIn(f"KEEL_CONFIG={real}/install/config.toml", unit)

    def test_install_says_which_config_the_service_will_read(self):
        """c-711 review: run from the checkout's own `bin/keel` with no `KEEL_CONFIG`, the
        install succeeds and changes nothing, so it says which file the service reads."""
        real = os.path.realpath(self.dir)
        os.mkdir(f"{real}/install")

        def said() -> str:
            out = io.StringIO()
            with mock.patch.object(voice.subprocess, "run"), redirect_stdout(out):
                self.assertEqual(voice.install(self.cfg, self.paths, load=False), 0)
            return out.getvalue()

        self.cfg.source = Path(f"{real}/install/config.toml")
        self.assertIn(f"the service reads {real}/install/config.toml\n", said())
        self.cfg.source = self.cfg.root / "etc" / "shipyard.example.toml"
        self.assertIn(f"the service reads {self.cfg.root}/etc/shipyard.example.toml, the checkout's own "
                      f"(no other config was named)\n", said())

    def test_the_checkouts_own_config_adds_nothing(self):
        for source in (None, self.cfg.root / "keel.toml", self.cfg.root / "config.toml"):
            self.cfg.source = source
            self.assertNotIn("KEEL_CONFIG", self.env(), source)

    def test_a_scratch_config_adds_nothing(self):
        self.cfg.source, self.cfg.scratch = self.dir / "other" / "config.toml", True
        self.assertNotIn("KEEL_CONFIG", self.env())

    def test_the_gateway_reads_its_judges_from_the_named_config(self):
        """The one file the gateway parses for itself is the file its `kb` loads."""
        named = self.dir / "install" / "config.toml"
        named.parent.mkdir()
        named.write_text('[voice.judges]\n"narrate" = "off"\n')
        home = self.dir / "checkout"
        home.mkdir()
        (home / "keel.toml").write_text('[voice.judges]\n"narrate" = "shadow"\n')
        self.assertEqual(vconfig.keel_toml(home, {"KEEL_CONFIG": str(named)}), named.resolve())
        self.assertEqual(vconfig.keel_toml(home, {}), home / "keel.toml")
        (home / "config.toml").write_text("")
        self.assertEqual(vconfig.keel_toml(home, {}), home / "config.toml")
        from harbor_voice import judges as vjudges
        with mock.patch.object(vconfig, "KEEL_TOML", vconfig.keel_toml(home, {"KEEL_CONFIG": str(named)})), \
             mock.patch.object(vconfig, "JUDGES_SWITCH", self.dir / "none.json"):
            self.assertEqual(vjudges.Switch().table()["narrate"]["mode"], "off")


class ReachesTheGatewayTest(VoiceCase):
    """c-711 review: what puts the config live, and that a child of the gateway keeps it."""

    def install_config(self) -> Path:
        self.cfg.source = self.dir / "install" / "config.toml"
        self.cfg.source.parent.mkdir()
        return self.cfg.source.resolve()

    def test_a_saved_voice_setting_reloads_the_service_with_the_installs_config(self):
        """`reload_if_loaded` is the deck's own re-render after a Settings save that touches
        `[voice]` (`keel/serve.py`): with `keel voice install --load`, one of the two acts
        that hand a loaded gateway its `KEEL_CONFIG`."""
        named = self.install_config()
        with mock.patch.object(voice.config_module, "load", return_value=self.cfg), \
             mock.patch.object(voice, "paths_from", return_value=self.paths), \
             mock.patch.object(service.Manager, "state", return_value=(True, 7)), \
             mock.patch.object(service.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
             redirect_stdout(io.StringIO()):
            self.assertTrue(voice.reload_if_loaded())
        loaded = self.paths.manager.installed_dir / "dev.keel.voice.plist"
        env = plistlib.loads(loaded.read_bytes())["EnvironmentVariables"]
        self.assertEqual(env["KEEL_CONFIG"], str(named))

    def test_the_service_names_the_state_dir_the_talker_writes_its_pid_in(self):
        env = voice.environment(self.cfg, self.paths, home=self.home)
        self.assertEqual(env["KEEL_STATE_DIR"], str(self.cfg.state_dir))

    def test_the_gateway_looks_for_the_talkers_pid_where_the_talker_writes_it(self):
        from keel import talker
        home, state = self.dir / "checkout", self.dir / "install" / "state"
        self.assertEqual(vconfig.keel_state(home, {}), home / "state")
        self.assertEqual(vconfig.keel_state(home, {"KEEL_STATE_DIR": str(state)}), state)
        written = talker.Paths(root=home, state_dir=state).pid_file
        self.assertEqual(vconfig.keel_state(home, {"KEEL_STATE_DIR": str(state)}) / "talker.pid",
                         written)
        written.parent.mkdir(parents=True)
        written.write_text(f"{os.getpid()}\n")
        # THE MODULE'S OWN CONSTANT, in a process started the way the service starts the
        # gateway: the package reads its paths once, at import, so only a fresh interpreter
        # can say what `TALKER_PID_FILE` is built from. `home` is a bare directory, so the
        # home is followed, and the talker's pid (this test's own) is found alive.
        home.mkdir()
        probe = ("from harbor_voice import config, snapshot; "
                 "print(config.TALKER_PID_FILE); print(snapshot._talker_up())")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "voice"),
               "KEEL_HOME": str(home), "KEEL_STATE_DIR": str(state)}
        done = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(done.stdout.split(), [str(written), "True"], done.stderr)
        env.pop("KEEL_STATE_DIR")
        done = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(done.stdout.split(), [str(home / "state" / "talker.pid"), "False"],
                         done.stderr)

    def probe(self, code: str, **env) -> str:
        """`code` in a fresh interpreter, started the way the service starts the gateway."""
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "voice"), **env}
        done = subprocess.run([sys.executable, "-c", "from harbor_voice import config; " + code],
                              env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_the_gateways_first_line_names_the_config(self):
        """What the owner reads in the log to know the reload took."""
        real = os.path.realpath(self.dir)
        os.makedirs(f"{real}/install")
        os.makedirs(f"{real}/bare")
        Path(f"{real}/install/config.toml").write_text("")
        line = self.probe("print(config.board_line())", KEEL_HOME=f"{real}/bare",
                          KEEL_CONFIG=f"{real}/install/config.toml")
        self.assertIn(f"  config {real}/install/config.toml  ", line)
        self.assertTrue(line.startswith("voice: board "), line)

    def test_a_borrowed_home_keeps_its_own_state_whatever_state_dir_it_inherited(self):
        """A gateway run from one checkout with `KEEL_HOME` naming ANOTHER keeps its own
        state (`config.borrows_home`); an inherited `KEEL_STATE_DIR` must not be the way
        round that, or a worktree's gateway would read the live talker's pid."""
        other = self.dir / "other"
        (other / "voice" / "harbor_voice").mkdir(parents=True)
        (other / "voice" / "harbor_voice" / "config.py").write_text("")
        said = self.probe("print(config.BORROWED_HOME); print(config.TALKER_PID_FILE)",
                          KEEL_HOME=str(other), KEEL_STATE_DIR=str(self.dir / "install" / "state"))
        self.assertEqual(said.split(), ["True", str(ROOT / "state" / "talker.pid")])

    def test_every_child_the_gateway_starts_keeps_the_named_config(self):
        """The gateway's `kb`, `keel` and Harbor turns are started with its own environment
        plus `KEEL_HOME`: a stand-in records the `KEEL_CONFIG` each one was handed."""
        from harbor_voice import connected, drawing, harbormsg, refineapply
        from harbor_voice import snapshot as vsnapshot
        named, seen = str(self.install_config()), self.dir / "seen"
        tools = self.dir / "tools"
        tools.mkdir()
        for name in ("kb", "keel", "claude"):
            fake_python(tools, name, f'printf "%s" "$KEEL_CONFIG" > "{seen}"; echo "{{}}"')
        (self.dir / "talker").mkdir()
        calls = {
            "snapshot._kb": lambda: vsnapshot._kb("list"),
            "refineapply.kb": lambda: refineapply.kb("show", "c-1", card="c-1"),
            "drawing.push_ops": lambda: drawing.push_ops("board: x\n"),
            "connected._run": lambda: connected._run(["c-1", "hello"], 10),
            "harbormsg.run_turn": lambda: harbormsg.run_turn("hello", 10, session="s", existed=False),
        }
        environ = {"KEEL_CONFIG": named, "PATH": f"{tools}:{os.environ.get('PATH', '')}"}
        with mock.patch.dict(os.environ, environ), \
             mock.patch.object(vconfig, "KB", tools / "kb"), \
             mock.patch.object(vconfig, "KEEL_BIN", tools / "keel"), \
             mock.patch.object(vconfig, "TALKER_CWD", self.dir / "talker"), \
             mock.patch.object(connected, "KEEL", str(tools / "keel")):
            for name, call in calls.items():
                seen.unlink(missing_ok=True)
                try:
                    call()
                except Exception:                                       # noqa: BLE001
                    pass        # what the stand-in answered is not the point; its env is
                self.assertEqual(seen.read_text() if seen.exists() else None, named, name)


class GoogleKeyTest(VoiceCase):
    """c-299: on Linux the Google key is the voice unit's systemd credential, its source a
    0600 file outside the checkout and outside state/, and no verb ever prints it."""

    KEY = "AIza-not-a-real-key"

    def linux(self):
        pin = mock.patch.object(service, "platform", return_value=service.SYSTEMD)
        pin.start()
        self.addCleanup(pin.stop)

    def set_key(self, text: str, loaded=(False, None)) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(service.Manager, "state", return_value=loaded), \
             mock.patch.object(service.Manager, "restart", return_value=(True, "systemctl --user restart")) as restart, \
             redirect_stdout(out):
            code = voice.key_set(self.paths, io.StringIO(text))
        self.restart = restart
        return code, out.getvalue()

    def test_the_unit_loads_the_credential_from_outside_the_checkout_and_state(self):
        self.linux()
        text = service.unit(voice.service(self.cfg, self.paths, python="/v/bin/python"))
        source = self.home / ".config" / "keel" / "credentials" / "google-tts-key"
        self.assertIn(f"LoadCredential=google-tts-key:{source}", text)
        self.assertNotIn(str(self.cfg.root), str(source))
        self.assertNotIn(str(self.cfg.state_dir), str(source))

    def test_the_name_is_the_one_the_gateway_reads(self):
        gateway_config = (Path(__file__).resolve().parent.parent / "voice" / "harbor_voice" / "config.py").read_text()
        self.assertIn(f'GOOGLE_TTS_CREDENTIAL = "{voice.GOOGLE_CREDENTIAL}"', gateway_config)

    def test_a_percent_in_the_source_is_not_a_unit_specifier(self):
        svc = voice.service(self.cfg, self.paths, python="p")
        svc.credentials = {"k": Path("/h/100%/k")}
        self.assertIn("LoadCredential=k:/h/100%%/k", service.unit(svc))

    def test_install_makes_an_empty_0600_source_so_the_unit_starts_without_a_key(self):
        """A missing source fails the unit with 243/CREDENTIALS (seen on systemd 255)."""
        self.linux()
        out = io.StringIO()
        with redirect_stdout(out):
            voice.install(self.cfg, self.paths, load=False)
        source = self.paths.credential
        self.assertEqual(source.read_bytes(), b"")
        self.assertEqual(source.stat().st_mode & 0o777, 0o600)
        self.assertEqual(source.parent.stat().st_mode & 0o777, 0o700)
        self.assertIn("keel voice key set", out.getvalue())

    def test_install_never_touches_a_key_that_is_there(self):
        self.linux()
        self.set_key(self.KEY)
        with redirect_stdout(io.StringIO()) as out:
            voice.install(self.cfg, self.paths, load=False)
        self.assertEqual(self.paths.credential.read_text(), self.KEY)
        self.assertNotIn("no Google key", out.getvalue())

    def test_the_mac_install_writes_no_credential_file(self):
        with redirect_stdout(io.StringIO()):
            voice.install(self.cfg, self.paths, load=False)
        self.assertFalse(self.paths.credential.exists())
        self.assertNotIn("LoadCredential", (self.paths.etc / "dev.keel.voice.plist").read_text())

    def test_set_writes_0600_from_stdin_and_never_prints_it(self):
        self.linux()
        code, out = self.set_key(self.KEY + "\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.paths.credential.read_text(), self.KEY)
        self.assertEqual(self.paths.credential.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.KEY, out)
        self.restart.assert_not_called()
        self.assertIn("install --load", out)

    def test_set_restarts_a_loaded_gateway_so_the_unit_copies_the_new_key(self):
        self.linux()
        self.install_unit("google-tts-key")
        code, out = self.set_key(self.KEY, loaded=(True, 42))
        self.assertEqual(code, 0)
        self.restart.assert_called_once_with(voice.LABEL)
        self.assertNotIn(self.KEY, out)
        self.assertIn("restarting voice so it reads the new Google TTS key", out)

    def test_set_refuses_nothing_and_anything_with_a_space(self):
        self.linux()
        for text in ("", "  \n", "two words"):
            code, _ = self.set_key(text)
            self.assertEqual(code, 1, text)
        self.assertFalse(self.paths.credential.exists() and self.paths.credential.read_text())

    def test_set_on_the_mac_points_at_the_keychain_and_writes_nothing(self):
        code, out = self.set_key(self.KEY)
        self.assertEqual(code, 2)
        self.assertIn("security add-generic-password", out)
        self.assertFalse(self.paths.credential.exists())

    def test_key_is_not_an_argument(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
             mock.patch("sys.stderr", io.StringIO()):
            voice.build_parser().parse_args(["key", "set", self.KEY])

    def test_check_says_missing_empty_or_set_and_never_the_value(self):
        self.linux()
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(voice.key_check(self.paths), 1)
        self.assertIn("MISSING", out.getvalue())
        voice.ensure_credential(self.paths)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(voice.key_check(self.paths), 1)
        self.assertIn("EMPTY", out.getvalue())
        self.set_key(self.KEY)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(voice.key_check(self.paths), 0)
        self.assertIn("set, mode 0600", out.getvalue())
        self.assertNotIn(self.KEY, out.getvalue())
        self.paths.credential.chmod(0o644)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(voice.key_check(self.paths), 1)
        self.assertIn("want 0600", out.getvalue())


class AudioTest(VoiceCase):
    """c-288: the rendered filler and ack clips. The box came up with 0 of 355, so the
    count is a verb bootstrap checks, and a render never runs without the preferred voice."""

    def run_audio(self, counts, render=False):
        out = io.StringIO()
        with mock.patch.object(voice, "audio_count", side_effect=counts), \
             mock.patch.object(voice.subprocess, "run") as run, redirect_stdout(out):
            code = voice.audio(self.cfg, self.paths, render=render)
        return code, out.getvalue(), run

    def test_every_clip_present_is_ok_and_renders_nothing(self):
        full = {"lines": 361, "rendered": 361, "missing": 0, "dir": "/c"}
        code, out, run = self.run_audio([full], render=True)
        self.assertEqual(code, 0)
        self.assertIn("361/361 lines have audio", out)
        run.assert_not_called()

    def test_a_short_count_fails_without_render(self):
        short = {"lines": 361, "rendered": 0, "missing": 361, "dir": "/c"}
        code, out, run = self.run_audio([short])
        self.assertEqual(code, 1)
        self.assertIn("361 missing", out)
        run.assert_not_called()

    def test_render_on_linux_refuses_without_the_google_key(self):
        pin = mock.patch.object(service, "platform", return_value=service.SYSTEMD)
        pin.start()
        self.addCleanup(pin.stop)
        short = {"lines": 361, "rendered": 0, "missing": 361, "dir": "/c"}
        code, out, run = self.run_audio([short], render=True)
        self.assertEqual(code, 1)
        self.assertIn("no Google key", out)
        run.assert_not_called()

    def test_render_runs_the_corpus_render_then_counts_again(self):
        short = {"lines": 361, "rendered": 5, "missing": 356, "dir": "/c"}
        full = {"lines": 361, "rendered": 361, "missing": 0, "dir": "/c"}
        code, out, run = self.run_audio([short, full], render=True)
        self.assertEqual(code, 0)
        argv = run.call_args.args[0]
        self.assertEqual(argv[1:], [str(self.cfg.root / "bin" / "keel-voice-corpus"), "render"])

    def test_the_count_reads_the_key_where_the_unit_would_put_it(self):
        pin = mock.patch.object(service, "platform", return_value=service.SYSTEMD)
        pin.start()
        self.addCleanup(pin.stop)
        env = voice.audio_environment(self.cfg, self.paths)
        self.assertEqual(env["CREDENTIALS_DIRECTORY"], str(self.paths.credential.parent))
        self.assertEqual(env["HARBOR_VOICE_TTS"], voice.LINUX_SPEECH["HARBOR_VOICE_TTS"])

    def test_a_set_per_engine_is_counted_and_named(self):
        """V7: the cache key names the engine, and he picks the engine per session, so
        "how many clips are there" is a question per set. A box with every Google clip
        and no Kokoro one would synthesise every filler live for a whole Kokoro session
        while a single total reported that nothing was missing."""
        both = {"lines": 722, "rendered": 361, "missing": 361, "dir": "/c", "sets": [
            {"engine": "google", "speaker": "harbor",
             "lines": 361, "rendered": 361, "missing": 0},
            {"engine": "kokoro", "speaker": "harbor",
             "lines": 361, "rendered": 0, "missing": 361}]}
        code, out, _run = self.run_audio([both])
        self.assertEqual(code, 1)
        self.assertIn("google as harbor: 361/361", out)
        self.assertIn("kokoro as harbor: 0/361, 361 missing", out)

    def test_a_set_per_speaker_is_counted_too(self):
        """V8: a connected house speaks in its own voice, so its fixed line is a clip of
        its own under a key of its own. Counting only Harbor's sets would report a full
        cache while the house's line was silent, which is the kind of thing found on the
        phone rather than in a test. The sets are lopsided on purpose, Harbor's hundreds
        against a house's one, and each is printed rather than summed."""
        sets = {"lines": 730, "rendered": 364, "missing": 366, "dir": "/c", "sets": [
            {"engine": "google", "speaker": "harbor",
             "lines": 364, "rendered": 364, "missing": 0},
            {"engine": "google", "speaker": "house",
             "lines": 1, "rendered": 0, "missing": 1},
            {"engine": "kokoro", "speaker": "harbor",
             "lines": 364, "rendered": 0, "missing": 364},
            {"engine": "kokoro", "speaker": "house",
             "lines": 1, "rendered": 0, "missing": 1}]}
        code, out, _run = self.run_audio([sets])
        self.assertEqual(code, 1)
        self.assertIn("google as harbor: 364/364", out)
        self.assertIn("google as house: 0/1, 1 missing", out)
        self.assertIn("kokoro as house: 0/1, 1 missing", out)

    def test_the_count_and_the_render_walk_the_same_sets(self):
        """One enumeration, two readers. The render fills the sets and this verb counts
        them, so a second list in either would be a cache that calls itself full while
        something in it is silent."""
        from keel import voice as voice_module
        self.assertIn("corpus.set_stats()", voice_module.AUDIO_COUNT)
        root = Path(__file__).resolve().parent.parent
        renderer = (root / "bin" / "keel-voice-corpus").read_text()
        self.assertIn("corpus.audio_sets(", renderer)

    def test_the_local_set_renders_on_linux_without_a_google_key(self):
        """The key is needed for the google set alone. Refusing the whole render because
        the cloud one cannot run would leave the local engine he CHOSE with no clips at
        all, which is the case the key is least relevant to."""
        pin = mock.patch.object(service, "platform", return_value=service.SYSTEMD)
        pin.start()
        self.addCleanup(pin.stop)
        local_short = {"lines": 722, "rendered": 361, "missing": 361, "dir": "/c", "sets": [
            {"engine": "google", "lines": 361, "rendered": 361, "missing": 0},
            {"engine": "kokoro", "lines": 361, "rendered": 0, "missing": 361}]}
        done = {"lines": 722, "rendered": 722, "missing": 0, "dir": "/c", "sets": [
            {"engine": "google", "lines": 361, "rendered": 361, "missing": 0},
            {"engine": "kokoro", "lines": 361, "rendered": 361, "missing": 0}]}
        code, out, run = self.run_audio([local_short, done], render=True)
        self.assertEqual(code, 0)
        self.assertNotIn("no Google key", out)
        run.assert_called_once()

    def test_the_google_set_still_refuses_on_linux_without_the_key(self):
        pin = mock.patch.object(service, "platform", return_value=service.SYSTEMD)
        pin.start()
        self.addCleanup(pin.stop)
        cloud_short = {"lines": 722, "rendered": 361, "missing": 361, "dir": "/c", "sets": [
            {"engine": "google", "lines": 361, "rendered": 0, "missing": 361},
            {"engine": "kokoro", "lines": 361, "rendered": 361, "missing": 0}]}
        code, out, run = self.run_audio([cloud_short], render=True)
        self.assertEqual(code, 1)
        self.assertIn("no Google key", out)
        run.assert_not_called()

    def test_no_venv_is_said_and_fails(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = voice.audio(self.cfg, self.paths)
        self.assertEqual(code, 1)
        self.assertIn("no .venv-voice", out.getvalue())


class InterpreterTest(VoiceCase):
    def test_the_newest_working_interpreter_at_or_below_the_ceiling_wins(self):
        fake_python(self.dir, "python3.12", "exit 1")                      # present but cannot make a venv
        fake_python(self.dir, "python3.11", "echo '(3, 11)'")
        fake_python(self.dir, "python3.10", "echo '(3, 10)'")
        self.assertEqual(voice.interpreter(roots=(str(self.dir) + "/",)), str(self.dir / "python3.11"))

    def test_a_missing_candidate_is_skipped_not_fatal(self):
        fake_python(self.dir, "python3.10", "echo '(3, 10)'")
        self.assertEqual(voice.interpreter(roots=(str(self.dir / "nowhere") + "/", str(self.dir) + "/")),
                         str(self.dir / "python3.10"))
        self.assertIsNone(voice.interpreter(roots=(str(self.dir / "nowhere") + "/",)))

    def test_venv_version_reads_the_pair_and_refuses_silence(self):
        self.assertIsNone(voice.venv_version(self.paths))
        self.paths.venv_python.parent.mkdir(parents=True)
        fake_python(self.paths.venv_python.parent, "python", "echo 3 12")
        self.assertEqual(voice.venv_version(self.paths), (3, 12))
        fake_python(self.paths.venv_python.parent, "python", "true")
        self.assertIsNone(voice.venv_version(self.paths))


class StatusTest(VoiceCase):
    def test_lines_when_up_and_when_down(self):
        lines = voice.status_lines(self.cfg, self.paths, True, 123, UP)
        self.assertEqual(lines[0], "voice: loaded (dev.keel.voice), pid 123")
        self.assertEqual(lines[1], "health: up 42.0s on 127.0.0.1:4391, stt parakeet-mlx, tts google, lookup tier removed")
        # A GATEWAY THAT REPORTS SOMETHING THIS LINE DOES NOT KNOW ABOUT still gets a
        # status line rather than a traceback: the subscript version of this raised a
        # KeyError the moment the gateway stopped reporting a router.
        self.assertIn("health: up 42.0s", voice.status_lines(self.cfg, self.paths, True, 1,
                                                             {"upSeconds": 42.0, "stt": {"ready": True}})[1])
        # FOUND, NOT COUNTED TO. This was `lines[2]`, which said "the third line is the
        # venv line" and broke the moment the detector got a line of its own above it
        # (c-311). What it is actually asserting is that a missing venv is called out.
        self.assertTrue(any("MISSING" in line for line in lines if line.startswith("venv:")))
        down = voice.status_lines(self.cfg, self.paths, False, None, None)
        self.assertEqual(down[:2], ["voice: not loaded (dev.keel.voice)", "health: not answering on 127.0.0.1:4391"])
        not_ready = dict(UP, stt={"backend": "none", "ready": False, "why": "parakeet-mlx did not load"})
        self.assertIn("        parakeet-mlx did not load", voice.status_lines(self.cfg, self.paths, True, 1, not_ready))

    def test_status_exit_code_follows_health(self):
        with mock.patch.object(voice, "loaded_pid", return_value=(True, None)), \
                mock.patch.object(voice, "health", return_value=None), redirect_stdout(io.StringIO()):
            self.assertEqual(voice.status(self.cfg, self.paths), 1)
        with mock.patch.object(voice, "loaded_pid", return_value=(True, None)), \
                mock.patch.object(voice, "health", return_value=UP), redirect_stdout(io.StringIO()):
            self.assertEqual(voice.status(self.cfg, self.paths), 0)


class NamedKeyTest(VoiceCase):
    """c-313: the judges' key joins the Google key's scheme rather than inventing one.
    Same directory, same 0600 in a 0700 dir, same verb with a name."""

    def linux(self):
        pin = mock.patch.object(service, "platform", return_value=service.SYSTEMD)
        pin.start()
        self.addCleanup(pin.stop)

    def set_key(self, text: str, name: str):
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
                redirect_stdout(io.StringIO()):
            return voice.key_set(self.paths, io.StringIO(text), name=name)

    def test_the_two_keys_are_separate_files_side_by_side(self):
        google, jev = self.paths.credential_for("google"), self.paths.credential_for("jev")
        self.assertEqual(google.name, "google-tts-key")
        self.assertEqual(jev.name, "jev-key")
        self.assertEqual(google.parent, jev.parent)
        self.assertEqual(self.paths.credential, google)
        self.assertNotIn(str(self.cfg.root), str(jev))          # outside the checkout
        self.assertNotIn(str(self.cfg.state_dir), str(jev))     # and outside state/

    def test_setting_the_jev_key_leaves_the_google_key_alone(self):
        self.linux()
        self.set_key("google-secret\n", "google")
        self.set_key("jev-secret\n", "jev")
        self.assertEqual(self.paths.credential_for("google").read_text(), "google-secret")
        self.assertEqual(self.paths.credential_for("jev").read_text(), "jev-secret")
        self.assertEqual(self.paths.credential_for("jev").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.paths.credential_for("jev").parent.stat().st_mode & 0o777, 0o700)

    def test_check_names_the_flag_that_would_fix_it_and_never_the_value(self):
        self.linux()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(voice.key_check(self.paths, name="jev"), 1)
        self.assertIn("keel voice key set --name jev", out.getvalue())
        self.set_key("jev-secret\n", "jev")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(voice.key_check(self.paths, name="jev"), 0)
        self.assertNotIn("jev-secret", out.getvalue())

    def test_it_says_before_it_restarts_a_live_service(self):
        """c-313, his note: the restart is the one thing this verb does to something that is
        running, so it is announced rather than discovered in a log."""
        self.linux()
        self.install_unit("jev-key")
        out = io.StringIO()
        with mock.patch.object(service.Manager, "state", return_value=(True, 42)), \
                mock.patch.object(service.Manager, "restart",
                                  return_value=(True, "systemctl --user restart")) as restart, \
                redirect_stdout(out):
            voice.key_set(self.paths, io.StringIO("jev-secret\n"), name="jev")
        said = out.getvalue()
        self.assertIn("restarting voice so it reads the new Jev API key", said)
        self.assertLess(said.index("restarting voice so it reads"), said.index("restarted voice"),
                        "it has to say so BEFORE it does it")
        self.assertEqual(restart.call_count, 1)

    def test_it_does_not_restart_for_a_credential_the_loaded_unit_cannot_use(self):
        """The live unit on the box had no LoadCredential= for jev-key, so the restart the
        verb performed bought nothing and still bounced a running gateway."""
        self.linux()
        self.install_unit("google-tts-key")
        out = io.StringIO()
        with mock.patch.object(service.Manager, "state", return_value=(True, 42)), \
                mock.patch.object(service.Manager, "restart",
                                  return_value=(True, "systemctl --user restart")) as restart, \
                redirect_stdout(out):
            code = voice.key_set(self.paths, io.StringIO("jev-secret\n"), name="jev")
        self.assertEqual(code, 0)
        self.assertEqual(restart.call_count, 0, "it restarted a live service for nothing")
        self.assertIn("NOT restarting voice", out.getvalue())
        self.assertIn("keel voice install --load", out.getvalue())
        self.assertEqual(self.paths.credential_for("jev").read_text(), "jev-secret",
                         "the key is still written: only the restart is skipped")

    def test_with_no_installed_unit_at_all_there_is_nothing_to_restart_for(self):
        self.linux()
        out = io.StringIO()
        with mock.patch.object(service.Manager, "state", return_value=(True, 42)), \
                mock.patch.object(service.Manager, "restart", return_value=(True, "x")) as restart, \
                redirect_stdout(out):
            voice.key_set(self.paths, io.StringIO("jev-secret\n"), name="jev")
        self.assertEqual(restart.call_count, 0)

    def test_the_verb_takes_the_name(self):
        args = voice.build_parser().parse_args(["key", "check", "--name", "jev"])
        self.assertEqual((args.verb, args.action, args.name), ("key", "check", "jev"))
        self.assertEqual(voice.build_parser().parse_args(["key", "check"]).name, "google")


class BenchTest(unittest.TestCase):
    """`bin/keel-jev-bench`: the arithmetic of B0's table, and the two refusals that stop
    a run from going out without a key or without a declared retention route (c-295)."""

    @staticmethod
    def bench():
        import importlib.util
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_loader(
            "keel_jev_bench",
            importlib.machinery.SourceFileLoader("keel_jev_bench", str(root / "bin" / "keel-jev-bench")))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def rows(mode, seconds):
        return [{"mode": mode, "i": i, "seconds": s, "status": 200, "fresh_connection": mode == "fresh"}
                for i, s in enumerate(seconds)]

    def test_the_first_call_is_reported_alone_and_left_out_of_the_percentiles(self):
        bench = self.bench()
        summary = bench.summarise(self.rows("fresh", [0.9, 0.1, 0.2, 0.3, 0.4]))
        self.assertEqual(summary["first"], 0.9)
        self.assertEqual(summary["max"], 0.4)       # the first call is not the max
        self.assertEqual(summary["p50"], 0.2)
        self.assertEqual(summary["n"], 5)
        self.assertEqual(summary["failed"], 0)

    def test_a_failed_call_is_counted_and_never_timed(self):
        bench = self.bench()
        rows = self.rows("fresh", [0.4, 0.2]) + [{"mode": "fresh", "i": 2, "seconds": None,
                                                  "status": 0, "error": "boom"}]
        summary = bench.summarise(rows)
        self.assertEqual((summary["n"], summary["failed"]), (3, 1))
        self.assertEqual(summary["p50"], 0.2)
        self.assertIn("(1 failed)", bench.table({"box": rows}))

    def test_every_label_gets_its_own_row_per_mode(self):
        bench = self.bench()
        text = bench.table({"box": self.rows("fresh", [0.5, 0.5]) + self.rows("keep-alive", [0.5, 0.3]),
                            "mac": self.rows("fresh", [0.8, 0.8])})
        self.assertEqual(text.count("| box |"), 2)
        self.assertEqual(text.count("| mac |"), 1)

    def test_it_refuses_to_send_anything_without_a_declared_retention_route(self):
        bench = self.bench()
        with mock.patch.object(bench, "retention", return_value=""):
            self.assertIn("does not exist", bench.refuse_without_retention())
        with mock.patch.object(bench, "retention", return_value="whatever"):
            self.assertIn("not one of", bench.refuse_without_retention())
        with mock.patch.object(bench, "retention", return_value="accept-default-retention"):
            self.assertIsNone(bench.refuse_without_retention())

    def test_a_missing_key_stops_the_run_and_says_where_the_key_goes(self):
        bench = self.bench()
        out = io.StringIO()
        args = bench.build_parser().parse_args(["b0", "--label", "box"])
        with mock.patch.object(bench, "retention", return_value="accept-default-retention"), \
                mock.patch.object(bench, "read_key", return_value=""), redirect_stdout(out):
            self.assertEqual(bench.b0(args), 1)
        self.assertIn("no Jev key on this machine", out.getvalue())
        # This machine's own line, then both branches read directly: the box is told the
        # verb and the Mac the keychain command, and a test that asserted one of them was
        # red on the other machine.
        self.assertIn(bench.how_to_put_it_there(), out.getvalue())
        self.assertIn("keel voice key set --name jev", bench.how_to_put_it_there("linux"))
        self.assertIn("security add-generic-password", bench.how_to_put_it_there("darwin"))
        self.assertIn("login keychain", bench.where_the_key_lives("darwin"))

    def test_c295s_own_lines_are_good_calls_although_they_carry_no_status(self):
        """The `mac` row of the same table was written before this script existed and has no
        `status` field. Requiring `status == 200` reported that whole run as 100 failures,
        which is what merging the two tables the first time actually did."""
        bench = self.bench()
        old_line = {"mode": "fresh", "i": 0, "seconds": 0.8069, "fresh_connection": True,
                    "request_id": "req_01a0b95023ef", "usage": {"input_tokens": 389}}
        self.assertTrue(bench.good_call(old_line))
        self.assertFalse(bench.good_call({**old_line, "error": "boom"}))
        self.assertFalse(bench.good_call({"mode": "fresh", "i": 0, "seconds": None}))
        self.assertFalse(bench.good_call({"mode": "fresh", "seconds": 0.5, "status": 500}))
        summary = bench.summarise([old_line, {**old_line, "i": 1, "seconds": 0.9}])
        self.assertEqual(summary["failed"], 0)

    def test_the_two_machines_land_in_one_table(self):
        bench = self.bench()
        text = bench.table({"box": self.rows("keep-alive", [0.8, 0.35]),
                            "mac": [{"mode": "keep-alive", "i": 0, "seconds": 0.8},
                                    {"mode": "keep-alive", "i": 1, "seconds": 0.34}]})
        self.assertIn("| box | keep-alive |", text)
        self.assertIn("| mac | keep-alive |", text)
        self.assertNotIn("failed", text)


class HealthTest(unittest.TestCase):
    def test_nothing_on_the_port_is_none(self):
        import socket
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.assertIsNone(voice.health(port, timeout=1))


class TwoStageRuleTest(unittest.TestCase):
    """D-6: the two-stage end-of-utterance rule, SCORED ONLY, never live. At a short pause
    the buffered audio is transcribed; the turn ends there when the words look finished,
    and otherwise waits for the long pause. `bin/keel-voice-vad-measure --two-stage`
    replays it over the corpus through these functions."""

    FRAME = 0.1

    def flags(self, *runs):
        out = []
        for speech, seconds in runs:
            out += [speech] * round(seconds / self.FRAME)
        return out

    def test_what_looks_finished(self):
        for text in ("Book the flights for Friday.", "what is building", "ok thanks"):
            self.assertTrue(vvad.looks_complete(text), text)
        for text in ("", "move the card and", "so the thing is, um", "I think the",
                     "check the export,"):
            self.assertFalse(vvad.looks_complete(text), text)

    def test_a_finished_sentence_ends_at_the_short_pause(self):
        at, stage = vvad.two_stage_fire_at(self.flags((True, 1.0), (False, 3.0)), self.FRAME,
                                           lambda seconds: "book the flights",
                                           short=0.7, long=2.0, min_speech=0.3)
        self.assertEqual(stage, "short")
        self.assertAlmostEqual(at, 1.7)

    def test_an_unfinished_one_waits_for_the_long_pause(self):
        at, stage = vvad.two_stage_fire_at(self.flags((True, 1.0), (False, 3.0)), self.FRAME,
                                           lambda seconds: "move the card and",
                                           short=0.7, long=2.0, min_speech=0.3)
        self.assertEqual(stage, "long")
        self.assertAlmostEqual(at, 3.0)

    def test_speech_after_an_unfinished_pause_asks_again_at_the_next(self):
        asked = []

        def heard(seconds):
            asked.append(round(seconds, 1))
            return "move the card and" if len(asked) == 1 else "move the card and archive it"
        at, stage = vvad.two_stage_fire_at(
            self.flags((True, 1.0), (False, 1.0), (True, 1.0), (False, 3.0)), self.FRAME,
            heard, short=0.7, long=2.0, min_speech=0.3)
        self.assertEqual((stage, asked), ("short", [1.7, 3.7]))
        self.assertAlmostEqual(at, 3.7)

    def test_silence_before_any_speech_never_fires(self):
        at, stage = vvad.two_stage_fire_at(self.flags((False, 5.0)), self.FRAME,
                                           lambda seconds: "anything", short=0.7, long=2.0,
                                           min_speech=0.3)
        self.assertEqual((at, stage), (None, ""))


if __name__ == "__main__":
    unittest.main()


class EndpointerTest(unittest.TestCase):
    """When the gateway decides he has stopped talking.

    THE ARITHMETIC IS THE WHOLE RISK. Everything else in this slice degrades safely: no
    model means no detector means today's behaviour. A hangover that is a frame too short
    cuts him off mid-sentence, on his own phone, and there is nothing to fall back to.
    """

    def test_it_fires_one_hangover_after_the_last_word(self):
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.096)
        # 10 frames of speech, then silence. 0.32s is ten 32 ms frames of it.
        at = _run(ep, "." * 10 + " " * 30)
        self.assertIsNotNone(at)
        self.assertAlmostEqual(at, (10 + 10) * FRAME, places=6)

    def test_silence_before_any_speech_never_fires(self):
        """A listen nobody has started talking into is not a finished utterance.

        Without this a quiet room ends the turn on its own and the gateway answers
        "nothing was heard" a second after the page started listening. Ending THAT is the
        page's twenty second backstop's job, not the detector's.
        """
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.096)
        self.assertIsNone(_run(ep, " " * 200))

    def test_a_cough_is_not_enough_speech_to_arm_it(self):
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.32)
        self.assertIsNone(_run(ep, "." * 2 + " " * 100))

    def test_a_pause_shorter_than_the_hangover_does_not_end_the_turn(self):
        """The reason the shipped number is 2.5 s and not 0.7 s: a pause mid-thought."""
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.096)
        at = _run(ep, "." * 10 + " " * 5 + "." * 10 + " " * 30)
        self.assertIsNotNone(at)
        self.assertAlmostEqual(at, (10 + 5 + 10 + 10) * FRAME, places=6)

    def test_the_silence_run_restarts_on_every_word(self):
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.096)
        for _ in range(5):
            self.assertFalse(ep.feed(True, FRAME))
        for _ in range(9):
            self.assertFalse(ep.feed(False, FRAME))
        self.assertFalse(ep.feed(True, FRAME))          # one more word
        for _ in range(9):
            self.assertFalse(ep.feed(False, FRAME))     # the run started again
        self.assertTrue(ep.feed(False, FRAME))

    def test_it_fires_once_and_not_once_per_frame(self):
        """The caller sends a message on it, so a second True is a second `endpoint`.

        The page would then release a turn it has already released, and on a socket that
        keeps streaming (a hold nobody dropped) that is one message per 32 ms.
        """
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.096)
        self.assertIsNotNone(_run(ep, "." * 10 + " " * 11))
        self.assertFalse(any(ep.feed(False, FRAME) for _ in range(50)))
        self.assertFalse(any(ep.feed(True, FRAME) for _ in range(50)))

    def test_reset_throws_away_the_speech_it_had_heard(self):
        """Reset, not pause, and this is the difference the brief asked for.

        While the gateway is speaking the detector is reset on every frame, so when it
        stops, fresh speech has to arrive before any hangover can run. Without that, the
        speech heard BEFORE the gateway started talking would still count as the arming
        speech, and the gateway's own voice leaking past the echo canceller would end a
        turn he had not begun.
        """
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.096)
        for _ in range(10):
            ep.feed(True, FRAME)
        self.assertTrue(ep.armed)
        ep.reset()
        self.assertFalse(ep.armed)
        self.assertIsNone(_run(ep, " " * 100))


    def test_a_failed_detector_is_disarmed_for_the_listen_rather_than_retried(self):
        """One bad frame must not become a log line every 32 ms.

        `Gateway.hear` sets `failed` and logs once; from then on the endpointer answers
        False whatever it is fed, so the turn ends on the page's own backstop, which is
        what it did before this card. `reset` clears it, because the next listen deserves
        a working detector.
        """
        ep = vvad.Endpointer(hangover=0.32, min_speech=0.096)
        ep.failed = True
        self.assertIsNone(_run(ep, "." * 20 + " " * 100))
        ep.reset()
        self.assertFalse(ep.failed)
        self.assertIsNotNone(_run(ep, "." * 10 + " " * 20))

    def test_a_missing_model_degrades_to_a_detector_that_never_fires(self):
        """No wheel, no model, no detector: hands-free waits the page out, as it did.

        This is what the Mac gets until its next `keel voice venv`, and it is why the
        Mac's requirements line could be landed unverified.
        """
        null = vvad.make_vad("off")
        self.assertFalse(null.ready)
        self.assertFalse(null.is_speech(b"\x00" * 1024))


class CorpusTest(unittest.TestCase):
    """The recorder's housekeeping. It is his voice, so the guards are tested."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "pcm"
        patch = mock.patch.object(vrecord.config, "RECORD_DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)
        on = mock.patch.object(vrecord.config, "RECORD_ENABLED", True)
        on.start()
        self.addCleanup(on.stop)

    def _write(self, name: str, seconds: float = 0.5) -> str:
        return vrecord.write(b"\x00\x00" * int(16000 * seconds), name)

    def test_off_by_default_writes_nothing(self):
        with mock.patch.object(vrecord.config, "RECORD_ENABLED", False):
            self.assertEqual(self._write("a"), "")
        self.assertFalse(self.dir.exists())

    def test_it_writes_a_readable_wav_at_the_microphone_rate(self):
        import wave
        self.assertEqual(self._write("a"), "a.wav")
        with wave.open(str(self.dir / "a.wav"), "rb") as fh:
            self.assertEqual(fh.getnchannels(), 1)
            self.assertEqual(fh.getsampwidth(), 2)
            self.assertEqual(fh.getframerate(), 16000)
            self.assertEqual(fh.getnframes(), 8000)

    def test_no_part_file_is_left_behind(self):
        """A gateway killed mid-write must not leave a half wav for the sweep to read."""
        self._write("a")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.wav"])

    def test_the_expiry_deletes_recordings_older_than_the_keep_days(self):
        self._write("old")
        self._write("new")
        old = self.dir / "old.wav"
        stale = time.time() - 20 * 86400
        os.utime(old, (stale, stale))
        with mock.patch.object(vrecord.config, "RECORD_KEEP_DAYS", 14.0):
            vrecord.sweep()
        self.assertFalse(old.exists())
        self.assertTrue((self.dir / "new.wav").exists())

    def test_the_cap_deletes_the_oldest_first(self):
        for name in ("a", "b", "c"):
            self._write(name, seconds=1.0)
            os.utime(self.dir / f"{name}.wav",
                     (time.time() - {"a": 300, "b": 200, "c": 100}[name],) * 2)
        with mock.patch.object(vrecord.config, "RECORD_MAX_MB", 0.05):
            vrecord.sweep()
        left = sorted(p.name for p in self.dir.glob("*.wav"))
        self.assertNotIn("a.wav", left)
        self.assertIn("c.wav", left)

    def test_the_utterance_just_spoken_is_never_the_one_thrown_away(self):
        """The sweep runs AFTER the write, so a tiny cap cannot eat the new recording."""
        with mock.patch.object(vrecord.config, "RECORD_MAX_MB", 0.0001):
            self.assertEqual(self._write("fresh"), "fresh.wav")
        self.assertTrue((self.dir / "fresh.wav").exists())

    def test_stats_say_whether_it_is_recording_as_well_as_what_is_there(self):
        self._write("a")
        stats = vrecord.stats()
        self.assertTrue(stats["recording"])
        self.assertEqual(stats["count"], 1)
        with mock.patch.object(vrecord.config, "RECORD_ENABLED", False):
            self.assertFalse(vrecord.stats()["recording"])
            self.assertEqual(vrecord.stats()["count"], 1)

    def test_delete_all_takes_the_recordings_and_leaves_everything_else(self):
        self._write("a")
        self._write("b")
        keeper = self.dir / "notes.txt"
        keeper.write_text("not a recording")
        self.assertEqual(vrecord.delete_all(), 2)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["notes.txt"])

    def test_the_recordings_are_readable_by_nobody_else(self):
        """0700 on the directory and 0600 on the wav, under the box's own umask.

        THE UMASK IS THE POINT OF THIS TEST. The first cut of record.py set no mode at
        all, so under umask 022 (the box's) the directory came out 0755 and every
        recording 0644: his voice, world readable, on a machine that runs a web server.
        Setting the umask here rather than trusting the runner's is what makes the test
        able to fail.
        """
        before = os.umask(0o022)
        self.addCleanup(os.umask, before)
        self.assertEqual(self._write("a"), "a.wav")
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.dir / "a.wav").stat().st_mode), 0o600)

    def test_the_mode_is_set_before_any_audio_is_written(self):
        """Not chmodded afterwards, which would leave a readable window mid-write.

        Asserted through the call `record.write` makes rather than by racing it: a test
        that tried to catch the window would be a flake. `os.open` with an explicit mode
        creates the file private; `builtins.open`, which `wave.open(str(path))` uses,
        creates it 0666 masked by the umask and could only be corrected after the fact.
        """
        seen = {}
        real = vrecord.os.open

        def spy(path, flags, mode=0o777, **kw):
            if str(path).endswith(".part"):
                seen["mode"] = mode
            return real(path, flags, mode, **kw)

        with mock.patch.object(vrecord.os, "open", spy):
            self._write("a")
        self.assertEqual(seen.get("mode"), 0o600)

    def test_recordings_already_on_disk_have_their_modes_repaired(self):
        """The ones written before this was fixed are still his voice.

        Both of the other paths that touch the corpus repair it, so a running gateway
        tidies itself on its next health poll rather than waiting for the next utterance.
        """
        self._write("old")
        os.chmod(self.dir / "old.wav", 0o644)
        os.chmod(self.dir, 0o755)
        vrecord.stats()
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.dir / "old.wav").stat().st_mode), 0o600)
        os.chmod(self.dir / "old.wav", 0o604)
        vrecord.sweep()
        self.assertEqual(stat.S_IMODE((self.dir / "old.wav").stat().st_mode), 0o600)


class CorpusExclusionTest(unittest.TestCase):
    """The recordings are his voice, so no archive may carry one.

    READ OUT OF THE SCRIPT rather than asserted against a run, the same way the rest of
    the backup's rules are checked: this is the line that decides it, and a rename of the
    directory that forgot this line would be silent until a year of him talking was in
    the archives.
    """

    def test_the_backup_prunes_the_recordings_directory(self):
        script = (Path(__file__).resolve().parent.parent / "bin" / "keel-backup").read_text()
        self.assertIn("-path 'state/voice/pcm'", script)


class DetectorConfigTest(VoiceCase):
    """The two keys reach the gateway, because the gateway never reads keel.toml."""

    def test_the_unit_carries_the_detector_and_the_recorder(self):
        self.cfg.voice_vad = "auto"
        self.cfg.voice_record = True
        env = voice.environment(self.cfg, self.paths, home=self.home)
        self.assertEqual(env["HARBOR_VOICE_VAD"], "auto")
        self.assertEqual(env["HARBOR_VOICE_RECORD"], "1")

    def test_off_is_the_one_line_back_to_the_twenty_second_backstop(self):
        self.cfg.voice_vad = "off"
        self.cfg.voice_record = False
        env = voice.environment(self.cfg, self.paths, home=self.home)
        self.assertEqual(env["HARBOR_VOICE_VAD"], "off")
        self.assertEqual(env["HARBOR_VOICE_RECORD"], "0")

    def test_harbor_kept_alive_ships_off_and_reaches_the_unit(self):
        """R2: the flag is off by default, and the unit says so either way."""
        self.assertFalse(Config.__dataclass_fields__["voice_harbor_kept_alive"].default)
        env = voice.environment(self.cfg, self.paths, home=self.home)
        self.assertEqual(env["HARBOR_VOICE_HARBOR_KEPT_ALIVE"], "0")
        self.cfg.voice_harbor_kept_alive = True
        env = voice.environment(self.cfg, self.paths, home=self.home)
        self.assertEqual(env["HARBOR_VOICE_HARBOR_KEPT_ALIVE"], "1")

    def test_harbor_kept_alive_is_read_from_the_voice_table(self):
        from keel import config as keel_config
        toml = self.dir / "flag.toml"
        toml.write_text(f'[keel]\nstate_dir = "{self.dir / "st"}"\n[voice]\nharbor_kept_alive = true\n')
        self.assertTrue(keel_config.load(toml, ensure=False).voice_harbor_kept_alive)

    def test_the_hangover_is_a_voice_key_and_ships_at_two_seconds(self):
        """H6 (lane H): approved at 2.0 s on the measured corpus (two-stage cut him
        mid-sentence 11 of 32 times, a plain 2.0 s 2 of 27). It travels like every other
        [voice] key (V4): keel.toml, then the unit's environment, never read by the gateway."""
        from keel import config as keel_config
        self.assertEqual(Config.__dataclass_fields__["voice_vad_hangover"].default, 2.0)
        toml = self.dir / "hang.toml"
        toml.write_text(f'[keel]\nstate_dir = "{self.dir / "st"}"\n[voice]\nvad_hangover = 1.5\n')
        self.assertEqual(keel_config.load(toml, ensure=False).voice_vad_hangover, 1.5)
        shipped = tomllib.loads((ROOT / "etc" / "shipyard.example.toml").read_text())
        self.assertEqual(shipped["voice"]["vad_hangover"], 2.0)

    def test_install_carries_the_hangover_into_the_unit(self):
        self.cfg.voice_vad_hangover = 2.0
        self.assertEqual(voice.environment(self.cfg, self.paths, home=self.home)
                         ["HARBOR_VOICE_VAD_HANGOVER"], "2.0")
        out = io.StringIO()
        with mock.patch.object(voice.subprocess, "run"), redirect_stdout(out):
            self.assertEqual(voice.install(self.cfg, self.paths, load=False), 0)
        plist = plistlib.loads((self.paths.etc / "dev.keel.voice.plist").read_bytes())
        self.assertEqual(plist["EnvironmentVariables"]["HARBOR_VOICE_VAD_HANGOVER"], "2.0")
        with mock.patch.object(service, "platform", return_value=service.SYSTEMD):
            unit = service.unit(voice.service(self.cfg, self.paths, python="/v/bin/python"))
        self.assertIn("HARBOR_VOICE_VAD_HANGOVER=2.0", unit)

    def test_status_says_the_configured_hangover_and_a_gateway_that_differs(self):
        self.cfg.voice_vad_hangover = 2.0
        lines = voice.status_lines(self.cfg, self.paths, True, 11, UP)
        self.assertTrue(any("hangover 2.5s, configured 2.0s" in l
                            and "keel voice install --load" in l for l in lines), lines)
        doc = dict(UP, vad=dict(UP["vad"], hangoverSeconds=2.0))
        lines = voice.status_lines(self.cfg, self.paths, True, 11, doc)
        self.assertTrue(any("hangover 2.0s (as configured)" in l for l in lines), lines)
        lines = voice.status_lines(self.cfg, self.paths, False, None, None)
        self.assertTrue(any("hangover configured 2.0s" in l for l in lines), lines)


    def test_status_says_the_hangover_when_a_detector_is_running(self):
        with mock.patch.object(voice, "health", return_value=UP):
            lines = voice.status_lines(self.cfg, self.paths, True, 11, UP)
        self.assertTrue(any("detector: silero, hangover 2.5s" in l for l in lines))

    def test_status_says_so_when_there_is_no_detector(self):
        doc = dict(UP, vad={"backend": "none", "ready": False, "why": "no model at /x",
                            "hangoverSeconds": 2.5})
        lines = voice.status_lines(self.cfg, self.paths, True, 11, doc)
        self.assertTrue(any("waits the page out" in l for l in lines))

    def test_status_names_the_corpus_once_there_is_one(self):
        doc = dict(UP, record={"recording": True, "count": 12, "megabytes": 3.4,
                               "oldestDays": 2.0})
        lines = voice.status_lines(self.cfg, self.paths, True, 11, doc)
        self.assertTrue(any("corpus: recording, 12 utterances" in l for l in lines))
        self.assertTrue(any("keel voice corpus --delete" in l for l in lines))


# `say -v ?` OUTPUT, IN ITS REAL SHAPE: a PADDED name column, then the locale, then `#`
# and a sample sentence. The padding is the whole point of having a fixture at all. Recent
# macOS lists names with spaces in them, and a name that fills the column is followed by ONE
# space while a short one is followed by a run of them, so a parser that splits on a run of
# spaces reads the long row's name as "Eddy (English (UK)) en_GB": a voice nothing has,
# asked for at the moment the chain is trying not to be silent. The first version of the
# probe did exactly that, and this fixture is what found it.
SAY_LIST = """\
Alex                en_US    # Most people recognize me by my voice.
Daniel              en_GB    # Hello, my name is Daniel. I am a British-English voice.
Eddy (English (UK)) en_GB    # Hello, my name is Eddy.
Veena               en_IN    # Hello, my name is Veena. I am an Indian-English voice.
"""


class SayVoiceProbeTest(unittest.TestCase):
    """The macOS synthesiser's voice probe (c-316, V8; one voice since V13).

    WHY THIS IS A PROBE AT ALL, and it outlives the second voice it was built for.
    `say -v <a voice this Mac lacks>` exits non-zero and writes no file, which
    `SayTTS._one` swallows into b"": that is SILENCE, from an engine that looked like it
    worked, in the one chain whose rule is degrade-never-mute. V8 needed it because
    `Veena` is an en_IN voice macOS offers and does not install; V13 took the house voice
    away, and `Daniel` is not guaranteed either, so the probe stays and the substitution
    it feeds is now the configured voice and nothing else.

    NOTHING IS EXECUTED HERE. `subprocess.run` is replaced for every case, so the fence
    sees no call at all, and `shutil.which` is replaced so the constructor gets past its
    "no `say` on this machine" guard on the box, which genuinely has none.
    """

    def build(self, run):
        """A `SayTTS` whose probe is `run`, with nothing on this machine touched."""
        with mock.patch.object(vspeech.shutil, "which", return_value="/usr/bin/say"), \
                mock.patch.object(vspeech.subprocess, "run", run):
            return vspeech.SayTTS()

    @staticmethod
    def listing(stdout="", returncode=0):
        def run(argv, **kwargs):
            run.calls.append(list(argv))
            return type("Done", (), {"returncode": returncode, "stdout": stdout,
                                     "stderr": ""})()
        run.calls = []
        return run

    def test_the_probe_asks_once_and_reads_a_padded_listing(self):
        run = self.listing(SAY_LIST)
        say = self.build(run)
        self.assertEqual(run.calls, [["say", "-v", "?"]], "the probe asks once, exactly")
        self.assertIn("Eddy (English (UK))", say.installed,
                      "a name with spaces in it was cut at the first one")
        self.assertEqual(say._resolve(say.voice), say.voice)

    def test_a_voice_this_mac_lacks_falls_to_the_configured_one(self):
        """The promise is kept by what is on the machine, not by what was hoped for: `say`
        asked for a voice it does not have writes no file, and an engine that looks like
        it worked and produced nothing is the one thing the chain may never be."""
        say = self.build(self.listing(SAY_LIST))
        self.assertNotIn("Rishi", say.installed)
        self.assertEqual(say._resolve("Rishi"), say.voice,
                         "a voice this Mac lacks must not be asked for")

    def test_there_is_one_voice_and_the_speaker_does_not_move_it(self):
        """V13: Harbor enters and leaves a house, so `say` speaks both roles the same way.
        Asserted through `config.voice_id` rather than on the engine, because that is the
        one place the decision lives and the engine only ever gets what it answers."""
        self.assertEqual(vconfig.voice_id("say", vconfig.SPEAKER_HOUSE),
                         vconfig.voice_id("say", vconfig.SPEAKER_HARBOR))
        self.assertEqual(vconfig.voice_id("say"), vconfig.TTS_SAY_VOICE)

    def test_a_probe_that_says_nothing_changes_nothing(self):
        """A `say` that exits non-zero, prints nothing or raises leaves `installed` empty,
        and then this engine behaves exactly as it did before the probe existed: it speaks
        its configured voice and asks for nothing it cannot have."""
        for why, run in (("exit 1", self.listing("", returncode=1)),
                         ("no output", self.listing("")),
                         ("raised", mock.Mock(side_effect=OSError("no such file")))):
            with self.subTest(why=why):
                say = self.build(run)
                self.assertEqual(say.installed, set())
                self.assertEqual(say._resolve("Rishi"), "Rishi",
                                 "an empty probe must not rewrite the call")
                self.assertEqual(say._resolve(say.voice), say.voice)
                # AND THE FALL IS REAL, not a hope. When `say` is then asked for a voice
                # this Mac lacks it writes no file and `_one` answers b"", so `synthesize`
                # YIELDS NOTHING, which `TTSChain` reads as "not an error and not a voice
                # either" and hands the sentence to the engine below rather than dropping
                # it (the chain's own half of that is in the selftest).
                with mock.patch.object(vspeech.SayTTS, "_one", return_value=b""):
                    spoke = list(say.synthesize("Leaving card 272. Back with you.",
                                                voice="Rishi"))
                self.assertEqual(spoke, [], "a mute engine must not look like a voice")


class TurnModelTest(VoiceCase):
    """B2: Keel's own voice turns name their model. The voice conversation and the refine
    share one session and one `run_turn`, and each invocation carries its own `--model`, so
    the conversation speaks on opus and the refine a capture gets runs on sonnet."""

    def test_the_service_file_carries_both_turn_models(self):
        self.cfg.turn_models = {"converse": "opus", "refine": "haiku"}
        env = voice.environment(self.cfg, self.paths, home=Path("/Users/me"))
        self.assertEqual(env["HARBOR_VOICE_CONVERSE_MODEL"], "opus")
        self.assertEqual(env["HARBOR_VOICE_REFINE_MODEL"], "haiku")


    def test_a_turn_names_the_conversation_model_unless_told_another(self):
        from harbor_voice import harbormsg
        argv = harbormsg.turn_command("hi", "s-1", True)
        self.assertEqual(argv[argv.index("--model") + 1], vconfig.CONVERSE_MODEL)
        argv = harbormsg.turn_command("hi", "s-1", True, model="sonnet")
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[-1], "hi")

    def test_the_refine_asks_for_its_own_model(self):
        from harbor_voice import harbormsg, refine
        seen = []

        def run(line, timeout, session, existed, model=None, **_scope):
            seen.append(model)
            return "quiet"

        with mock.patch.object(harbormsg, "open_session", return_value=("s-1", True, "")), \
                mock.patch.object(harbormsg, "count_turn"), mock.patch.object(harbormsg, "log"):
            refine.Refiner(run=run, topics=lambda space: []).refine(
                {"card": "c-1", "said": "a thing", "space": "personal"})
        self.assertEqual(seen, [vconfig.REFINE_MODEL])


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "harness"


def envelope(structured=None, result="") -> str:
    """The real `--output-format json --json-schema` envelope's shape (2.1.281, recorded in
    `tests/fixtures/harness/structured.json`), with this test's own answer in it."""
    real = json.loads((FIXTURES / "structured.json").read_text())
    real["result"] = result or (json.dumps(structured) if structured is not None else "")
    if structured is None:
        real.pop("structured_output", None)
    else:
        real["structured_output"] = structured
    return json.dumps(real)


class RefineScopeTurnTest(unittest.TestCase):
    """Rounds 2 and 3, item A: the refine turn has NO tools, keeps no session, and asks
    for a structured answer against a schema built per call. Nothing is run."""

    def turn(self, stdout=None, writes=None):
        from harbor_voice import harbormsg, refine
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs.get("env") or {}))
            return mock.Mock(returncode=0, stdout=stdout or envelope(None, "{}"), stderr="")

        def fake_kb(*argv, **_scope):
            if writes is not None and argv[:1] not in (("repos",), ("show",)):
                writes.append(argv)
            if argv[:1] == ("repos",):
                return [{"repo": "keel"}, {"repo": "harbor"}]
            return {}

        with mock.patch.object(harbormsg.subprocess, "run", fake_run), \
                mock.patch.object(harbormsg, "log"), \
                mock.patch.object(refine.refineapply, "kb", fake_kb):
            refine.Refiner(topics=lambda space: ["voice"]).refine(
                {"card": "c-7", "said": "block c-8", "space": "personal"})
        return calls[0]

    def test_the_turn_has_no_tools_and_no_session(self):
        argv, env = self.turn()
        self.assertEqual(argv[-2:], ["--tools", ""], "the empty value must be the last one")
        for flag in ("--no-session-persistence", "--strict-mcp-config",
                     "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertEqual(env.get("KEEL_REFINE_CARD"), "c-7")

    def test_the_turn_asks_for_structured_output_against_the_schema(self):
        argv, _env = self.turn()
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        schema = json.loads(argv[argv.index("--json-schema") + 1])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]))
        repo = json.dumps(schema["properties"]["repo"])
        self.assertIn('"keel"', repo)
        self.assertIn('"harbor"', repo)
        self.assertIn('"voice"', json.dumps(schema["properties"]["topic"]))
        self.assertEqual((schema["properties"]["split"]["anyOf"][0]["minItems"],
                          schema["properties"]["split"]["anyOf"][0]["maxItems"]), (2, 5))

    def test_the_structured_output_is_what_is_applied(self):
        from harbor_voice import refineapply
        good = {"title": "Fix it", "topic": None, "repo": "keel", "note": None,
                "question": None, "choices": [], "split": None, "line": "ok"}
        writes = []
        # THE STRUCTURED FIELD IS READ, NOT `result`: here `result` is prose.
        self.turn(stdout=envelope(good, result="Here is the refine."), writes=writes)
        self.assertIn(("--actor", "voice", "set", "c-7", "repo=keel", "--assumed", "repo"),
                      writes)

    def test_an_envelope_with_no_structured_output_changes_nothing(self):
        """The box's real no-schema answer: prose and a pretend tool call, then JSON."""
        good = {"title": "Fix it", "topic": None, "repo": "keel", "note": None,
                "question": None, "choices": [], "split": None, "line": "ok"}
        prose = "I'll run kb block c-8 now.\n<tool>kb block c-8</tool>\n" + json.dumps(good)
        writes = []
        self.turn(stdout=envelope(None, prose), writes=writes)
        self.assertEqual(writes, [])


REPOS = ["keel", "harbor"]


def answer(**over):
    base = {"title": None, "topic": None, "repo": None, "note": None, "question": None,
            "choices": [], "split": None, "line": "tidied"}
    base.update(over)
    return json.dumps(base)


class RefineAnswerTest(unittest.TestCase):
    """Round 2, item A: the refine's answer is ONE JSON object, parsed strictly, and Keel
    applies it to the captured card only."""

    def parse(self, text, topics=("voice", "boards")):
        from harbor_voice import refineapply
        return refineapply.parse(text, repos=REPOS, topics=list(topics))

    def test_a_good_answer_parses(self):
        got = self.parse(answer(title="Fix the export", repo="keel", topic="boards"))
        self.assertEqual((got["title"], got["repo"], got["topic"]),
                         ("Fix the export", "keel", "boards"))

    def test_malformed_answers_are_refused(self):
        from harbor_voice import refineapply
        bad = ["not json", "[]", answer()[:-1] + ', "extra": 1}',
               json.dumps({"title": "missing keys"}),
               answer(repo="webapp"), answer(topic="invented"),
               answer(title="x" * 200), answer(choices=["a", "b"]),
               answer(question="Which?", choices=["a"] * 9),
               answer(split=["only one"]), answer(split=["a"] * 9),
               answer(title=7), answer(line="")]
        for text in bad:
            with self.assertRaises(refineapply.Malformed, msg=text):
                self.parse(text)

    def test_a_fenced_answer_is_read(self):
        got = self.parse("```json\n" + answer(title="T") + "\n```")
        self.assertEqual(got["title"], "T")

    def apply(self, text, stated=()):
        from harbor_voice import refineapply
        calls = []

        def kb(*argv, card=""):
            calls.append((argv, card))
            if argv[:1] == ("show",):
                return {"id": "c-7", "options": {"provenance": {k: "stated" for k in stated}}}
            if "create" in argv:
                return {"id": f"c-{90 + len(calls)}"}
            return {}
        refineapply.apply(self.parse(text), "c-7", "personal", kb=kb)
        return calls

    def test_everything_lands_on_the_captured_card_as_voice(self):
        calls = self.apply(answer(title="Fix the export", repo="keel", topic="boards",
                                  note="A bug in the export.", question="Which export?",
                                  choices=["csv", "pdf"]))
        writes = [argv for argv, _card in calls if argv[:1] != ("show",)]
        self.assertTrue(all(card == "c-7" for _argv, card in calls))
        self.assertTrue(all(argv[:2] == ("--actor", "voice") for argv in writes))
        ids = {argv[3] for argv in writes if argv[2] in ("set", "note", "block")}
        self.assertEqual(ids, {"c-7"})
        self.assertIn(("--actor", "voice", "set", "c-7", "repo=keel", "topic=boards",
                       "--assumed", "repo,topic"), writes)
        self.assertIn(("--actor", "voice", "block", "c-7", "Which export?"), writes)
        self.assertIn(("--actor", "voice", "set", "c-7", 'options.choices=["csv", "pdf"]'),
                      writes)
        self.assertEqual(writes[-1], ("--actor", "voice", "set", "c-7",
                                      "options.capture=refined"))

    def test_a_stated_field_is_left_alone(self):
        calls = self.apply(answer(repo="keel", topic="boards"), stated=("repo",))
        writes = [argv for argv, _card in calls if argv[:1] != ("show",)]
        self.assertIn(("--actor", "voice", "set", "c-7", "topic=boards", "--assumed", "topic"),
                      writes)
        self.assertFalse([a for a in writes if "repo=keel" in a])

    def test_a_split_creates_inbox_children_from_the_card_with_no_parent(self):
        calls = self.apply(answer(split=["Book flights", "Pack bags"]))
        creates = [argv for argv, _card in calls if "create" in argv]
        self.assertEqual(len(creates), 2)
        for argv in creates:
            self.assertEqual(argv[argv.index("--from") + 1], "c-7")
            self.assertNotIn("--parent", argv)
            self.assertNotIn("--after", argv)
            self.assertEqual(argv[argv.index("--space") + 1], "personal")

    def test_a_malformed_answer_changes_nothing(self):
        from harbor_voice import harbormsg, refine
        writes = []
        with mock.patch.object(refine.refineapply, "kb",
                               lambda *a, **k: writes.append(a) or [{"repo": "keel"}]), \
                mock.patch.object(harbormsg, "log"):
            refine.Refiner(topics=lambda space: [], run=lambda *a, **k: "block c-8 now"
                           ).refine({"card": "c-7", "said": "x", "space": "personal"})
        self.assertEqual([a for a in writes if a[:1] != ("repos",)], [])


class HarborLiveLifetimeTest(unittest.TestCase):
    """Lane D review item 5: no kept-alive Harbor process outlives the gateway, and one
    handed to a turn is never closed as idle under it. Nothing real is started."""

    def setUp(self):
        from harbor_voice import harborlive
        self.live = harborlive.LiveHarbor()
        self.held = mock.Mock(alive=True, session="s-1", turns_seen=3, last_used=0.0)
        self.live.process = self.held

    def test_taking_the_process_stamps_it_used_under_the_lock(self):
        from harbor_voice import harborlive
        with mock.patch.object(harborlive.time, "monotonic", return_value=5000.0):
            got = self.live.process_for("s-1", True, 3)
        self.assertIs(got, self.held)
        self.assertEqual(self.held.last_used, 5000.0)
        with mock.patch.object(harborlive.config, "HARBOR_LIVE_IDLE", 600.0), \
                mock.patch.object(harborlive.time, "monotonic", return_value=5001.0):
            self.live.close_if_idle()
        self.held.close.assert_not_called()

    def test_exit_and_sigterm_drop_the_process(self):
        from harbor_voice import harborlive
        handlers, exits = {}, []
        with mock.patch.object(harborlive, "LIVE", self.live), \
                mock.patch.object(harborlive.atexit, "register", exits.append), \
                mock.patch.object(harborlive.signal, "signal",
                                  lambda sig, fn: handlers.__setitem__(sig, fn)), \
                mock.patch.object(harborlive.signal, "getsignal",
                                  return_value=harborlive.signal.SIG_DFL):
            harborlive.install_shutdown()
            self.assertTrue(exits)
            with self.assertRaises(SystemExit):
                handlers[harborlive.signal.SIGTERM](harborlive.signal.SIGTERM, None)
        self.held.close.assert_called_once()
        self.assertIsNone(self.live.process)


class GoogleConnectionTest(unittest.TestCase):
    """D-5: one TLS connection to Google TTS is reused across clips, not one per clip.

    A clip is one sentence and an answer is several, so a handshake per clip was paid on
    every sentence. The connection is a stand-in here; nothing reaches the network."""

    class FakeConn:
        made: list = []

        def __init__(self, host, timeout=None, context=None):
            self.host = host
            self.requests = []
            self.fail_next = False
            self.closed = False
            GoogleConnectionTest.FakeConn.made.append(self)

        def request(self, method, path, body=None, headers=None):
            if self.fail_next:
                failure, self.fail_next = self.fail_next, False
                raise (failure if isinstance(failure, BaseException)
                       else ConnectionResetError("the far end went away"))
            self.requests.append((method, path, headers))

        def getresponse(self):
            audio = __import__("base64").b64encode(b"RIFF").decode()
            body = __import__("json").dumps({"audioContent": audio}).encode()
            return type("R", (), {"status": 200, "read": lambda self: body})()

        def close(self):
            self.closed = True

    def setUp(self):
        GoogleConnectionTest.FakeConn.made = []
        patcher = mock.patch.object(vspeech.http.client, "HTTPSConnection", self.FakeConn)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tts = vspeech.GoogleTTS.__new__(vspeech.GoogleTTS)
        self.tts.voice, self.tts.language, self.tts.key = "v", "en-IN", "k"
        self.tts._pool, self.tts._pool_lock = [], vspeech.threading.Lock()

    def test_two_clips_share_one_connection(self):
        self.tts._request("one")
        self.tts._request("two")
        self.assertEqual(len(self.FakeConn.made), 1)
        self.assertEqual(len(self.FakeConn.made[0].requests), 2)

    def test_the_key_is_a_header_and_never_in_the_path(self):
        self.tts._request("one")
        method, path, headers = self.FakeConn.made[0].requests[0]
        self.assertEqual(headers["X-Goog-Api-Key"], "k")
        self.assertNotIn("k", path.replace("/v1/text:synthesize", ""))

    def test_a_timeout_on_a_reused_connection_is_never_resent(self):
        """Review item 6: a timeout may mean Google got the text; sending it again would
        bill and speak it twice. Only failures before any byte moved are retried."""
        self.tts._request("one")
        self.FakeConn.made[0].fail_next = TimeoutError("timed out")
        with self.assertRaises(TimeoutError):
            self.tts._request("two")
        self.assertEqual(len(self.FakeConn.made), 1)

    def test_a_remote_disconnect_on_a_reused_connection_is_resent_once(self):
        self.tts._request("one")
        self.FakeConn.made[0].fail_next = vspeech.http.client.RemoteDisconnected("closed")
        self.tts._request("two")
        self.assertEqual(len(self.FakeConn.made), 2)

    def test_a_reused_connection_that_died_is_replaced_once(self):
        self.tts._request("one")
        self.FakeConn.made[0].fail_next = True
        self.tts._request("two")
        self.assertEqual(len(self.FakeConn.made), 2)
        self.assertTrue(self.FakeConn.made[0].closed)
        self.assertEqual(len(self.FakeConn.made[1].requests), 1)
