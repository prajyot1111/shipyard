"""`keel voice`: the voice gateway's runtime, from Keel's side.

The gateway itself is `bin/keel-voice-gateway` running the `harbor_voice` package under
`voice/`, on its own 3.12 interpreter (`.venv-voice`), never imported here: `keel/` is
stdlib on 3.14 and the speech stack is pinned below 3.13. What lives here is what Keel
needs to know and do about the service:

    venv               build .venv-voice from etc/voice-requirements.txt on the newest
                       python3 the speech stack allows (MAX_PY, with the evidence beside it)
    install [--load]   write dev.keel.voice.plist (macOS) or dev.keel.voice.service into the
                       services directory (the install's services/, a bare checkout's etc/)
                       (Linux): the venv's python running the gateway, WorkingDirectory the
                       repo, logs to state/logs/voice.log, and the [voice] table plus the
                       paths as its environment, so the gateway keeps reading its
                       environment and never parses TOML. `--load` copies it where launchd
                       or systemd looks and starts it (`keel/service.py`)
    uninstall          stop it and remove the manager's copy
    status             loaded, pid, answering, and which speech backends answered
    key set|check [--name google|jev]
                       a key this machine holds, on Linux: `set` reads it from stdin into
                       the unit's systemd credential source and restarts the gateway;
                       `check` says whether it is there, never what it is (c-299). `google`
                       is the TTS key; `jev` is the judges' key (V10), which lives in the
                       same place by the same rule
    audio [--render]   how many of the filler and ack lines have a rendered clip, and with
                       --render, render the missing ones in the preferred voice
    judge <key> <mode> the judges' switch (V10): off, shadow, on, or default to hand the
                       key back to `[voice.judges]`. Writes the override the gateway reads
                       on its mtime, so a flip needs no restart (`keel/judges.py`)
    judges             what the shadow log says, per key: calls, agreement with the rule,
                       latency, misses, and the disagreements worth reading; with
                       --since YYYY-MM-DD [--days 7] [--labels PATH], the verdict per key
                       (flip on, drop, needs more data) on personal turns (c-552)
                       (`bin/keel-voice-corpus render`, as the gateway's own environment
                       would); exits 0 only when none is missing (c-288)

`health(port)` is the probe `keel doctor` reads too. Everything the verbs know comes
from the install's `config.toml` through `keel.config`: the repo root gives the venv, the requirements,
the gateway script and the service file; the state dir gives the log and the data directory.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from keel import config as config_module, judges as judges_module, service as service_module
from keel import judgeverdict, packs
from keel import voicelatency

LABEL = "dev.keel.voice"
HEALTH_TIMEOUT = 2.0
# ITS SHARE OF THE CPU AGAINST THE ENGINE'S UNIT, where the houses live (systemd only).
# The drain renices every house, but nice orders processes only inside one cgroup, and on
# Linux the gateway and the houses are in different ones: 400 against the engine's 100
# gives a spoken turn four fifths of a contended core. launchd has no counterpart; there
# nice alone does it.
VOICE_CPU_WEIGHT = 400

# THE NEWEST INTERPRETER IS THE WRONG ONE. `python3` on this machine is whatever brew
# upgraded to last (3.14 today), and the speech stack cannot install there: the ceiling
# is kokoro's own metadata, `kokoro 0.9.4  Requires-Python >=3.10,<3.13`, which pip
# refuses on 3.13 and 3.14 before any wheel is fetched. It is NOT blis, the reason once
# on record; blis and spacy have shipped 3.14 wheels since 2026-09-04 (checked, not
# assumed). Raise MAX_PY when kokoro itself widens that pin and `keel voice venv` has
# actually been run against the new interpreter, never on the strength of a dependency's
# wheel. The search below is versioned names only, newest first, so a bare `python3` is
# never chosen by accident.
MAX_PY = (3, 12)
MIN_PY = (3, 10)
INTERPRETER_ROOTS = ("/opt/homebrew/bin/", "/usr/local/bin/", "")

# WHAT THE BOX HEARS AND SPEAKS WITH, written into the unit on Linux (c-286). The Mac's
# engines are Apple-silicon builds (parakeet-mlx, torch kokoro with brew's espeak-ng), so
# on Linux the unit names the ONNX pair instead: sherpa-onnx Parakeet for speech in, and
# kokoro-onnx beneath Google for speech out. `say` is macOS only, so it is not in the
# box's chain. The gateway's own defaults stay the Mac's; a unit on macOS adds nothing.
LINUX_SPEECH = {"HARBOR_VOICE_STT": "sherpa", "HARBOR_VOICE_TTS": "google,kokoro-onnx,browser"}

# WHERE THE GOOGLE KEY LIVES ON LINUX (c-299, his call on 2026-09-19). The Mac keeps it in
# the login keychain; the box has none, so the unit loads it as a systemd credential and
# the gateway reads `$CREDENTIALS_DIRECTORY/google-tts-key`. The name must equal
# `harbor_voice.config.GOOGLE_TTS_CREDENTIAL` (tests/test_voice.py holds them together).
# The source is a 0600 file in a 0700 dir under ~/.config: outside the checkout, so no
# `git add -A` commits it, and outside state/, so no backup carries it. Ubuntu 24.04 is
# systemd 255, where a user unit cannot hold an encrypted credential (`systemd-creds
# --user` is 256), so at rest it is plaintext; on 256 this becomes SetCredentialEncrypted=
# with nothing in the gateway changing.
GOOGLE_CREDENTIAL = "google-tts-key"
KEYCHAIN_SERVICE = "harbor-voice-google"

# The same rule, for every key this machine holds: one credential name, one keychain
# service, one label for the prompt. V10's judges key joins it rather than inventing a
# second scheme, so `keel voice key set --name jev` is the Google verb with a name.
KEYS = {
    "google": (GOOGLE_CREDENTIAL, KEYCHAIN_SERVICE, "Google TTS key"),
    "jev": ("jev-key", "harbor-voice-jev", "Jev API key"),
}


@dataclass
class Paths:
    root: Path
    state_dir: Path
    # WHOSE `Library/LaunchAgents` (or `.config/systemd/user`) THE LOADED COPY LIVES IN.
    # Defaulted rather than required, so every existing caller is unchanged, and passed
    # explicitly by the tests so a `--load` test cannot touch the live agent: resolved
    # against the process's real home, one once did (`keel/backup.py`, LAUNCH_AGENTS).
    home: Path = field(default_factory=Path.home)
    # Where its service file is rendered (c-722, `Config.services_dir`): the install's
    # `services/`. None: the checkout's `etc/`.
    services: Path | None = None

    @property
    def venv(self) -> Path:
        return self.root / ".venv-voice"

    @property
    def venv_python(self) -> Path:
        return self.venv / "bin" / "python"

    @property
    def requirements(self) -> Path:
        return self.root / "etc" / "voice-requirements.txt"

    @property
    def gateway(self) -> Path:
        return self.root / "bin" / "keel-voice-gateway"

    @property
    def log(self) -> Path:
        return self.state_dir / "logs" / "voice.log"

    @property
    def data(self) -> Path:
        """The gateway's writable surface (`harbor_voice.config.DATA`)."""
        return self.state_dir / "voice"

    @property
    def etc(self) -> Path:
        return self.services or self.root / "etc"

    @property
    def credential(self) -> Path:
        """The Google key's source file on Linux, read by systemd, never by the gateway."""
        return self.credential_for("google")

    def credential_for(self, name: str) -> Path:
        """One key's source file on Linux: 0600 in a 0700 dir, outside the checkout and
        outside state/, so neither a commit nor a backup ever carries it."""
        return credentials_dir(self.home) / KEYS[name][0]

    @property
    def manager(self) -> service_module.Manager:
        return service_module.Manager(self.home)


def credentials_dir(home: Path | None = None) -> Path:
    """Where the keys this machine holds live, whoever needs one.

    One directory and one rule, so a key added later is not a second scheme: 0700 under
    `~/.config`, outside the checkout so no `git add -A` commits it, and outside `state/`
    so no backup carries it. The Google and Jev keys are here because systemd loads them
    as credentials; the SHARED HOUSE KEY (V12 slice 2, `keel/housetier.py`) is here for the
    same reason the others are, and it is read by Keel itself rather than by a unit.
    """
    return (home or Path.home()) / ".config" / "keel" / "credentials"


def paths_from(cfg) -> Paths:
    return Paths(root=cfg.root, state_dir=cfg.state_dir, home=cfg.home,
                 services=getattr(cfg, "services_dir", None))


# ----- health -----

def health(port: int, timeout: float = HEALTH_TIMEOUT) -> dict | None:
    """The gateway's `/voice/health` document, or None when nothing answers on the port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/voice/health", timeout=timeout) as response:
            return json.load(response)
    except Exception:  # noqa: BLE001 - down is down, whatever the reason
        return None


# ----- venv -----

def interpreter(roots: tuple[str, ...] = INTERPRETER_ROOTS) -> str | None:
    """The newest python3 that can build a venv AND is no newer than MAX_PY.

    A missing executable is not a non-zero exit: `subprocess.run` raises when the program
    is not there, so each candidate is tried in turn rather than the search stopping at
    the first name this machine does not have.
    """
    names = [f"python3.{minor}" for minor in range(MAX_PY[1], MIN_PY[1] - 1, -1)]
    for name in names:
        for root in roots:
            candidate = root + name
            try:
                probe = subprocess.run([candidate, "-c", "import venv,sys; print(sys.version_info[:2])"],
                                       capture_output=True, text=True)
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                continue
            if probe.returncode == 0:
                return candidate
    return None


def venv_version(paths: Paths) -> tuple[int, int] | None:
    """(major, minor) of the interpreter in .venv-voice, or None when it cannot say. An
    interpreter that runs and prints nothing is None too, not an empty tuple."""
    if not paths.venv_python.exists():
        return None
    try:
        probe = subprocess.run([str(paths.venv_python), "-c",
                                "import sys; print(sys.version_info[0], sys.version_info[1])"],
                               capture_output=True, text=True)
    except OSError:
        return None
    parts = probe.stdout.split()
    if probe.returncode != 0 or len(parts) < 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def build_venv(paths: Paths) -> int:
    """`keel voice venv`: reaches PyPI, so a person runs it on purpose. An existing venv
    outside the MIN_PY..MAX_PY range (in either direction) is rebuilt, not reused, because
    pip would refuse kokoro inside it and the gateway would come up without a voice."""
    if not paths.requirements.exists():
        print(f"keel voice venv: no {paths.requirements}", file=sys.stderr)
        return 2
    base = interpreter()
    if base is None:
        print(f"keel voice venv: no python3 at {MAX_PY[0]}.{MAX_PY[1]} or below that can make a venv. "
              "Install one: brew install python@3.12", file=sys.stderr)
        return 2
    have = venv_version(paths)
    if have is not None and not (MIN_PY <= have <= MAX_PY):
        print(f"keel voice venv: {paths.venv} is Python {have[0]}.{have[1]}, outside the "
              f"{MIN_PY[0]}.{MIN_PY[1]} to {MAX_PY[0]}.{MAX_PY[1]} range the speech stack installs "
              f"under. Rebuilding it with {base}.", file=sys.stderr)
        have = None
    if have is None:
        shutil.rmtree(paths.venv, ignore_errors=True)   # a half-built tree is not fixed in place
        subprocess.run([base, "-m", "venv", str(paths.venv)], check=True)
    code = subprocess.run([str(paths.venv_python), "-m", "pip", "install", "-r", str(paths.requirements)]).returncode
    if code:
        return code
    print(f"built {paths.venv} (python {'.'.join(map(str, venv_version(paths) or ()))})")
    return 0


# ----- install -----

def environment(cfg, paths: Paths, home: Path | None = None) -> dict[str, str]:
    """What the service's process gets. launchd and systemd hand a service almost no
    environment, and everything the gateway shells out to (`kb`, `claude`) or reads (its
    port, its data) comes from here. `CLAUDE_CONFIG_DIR` is deliberately absent:
    `harbormsg` sets it per turn, so the gateway's own process never holds the talker's
    rules or credentials."""
    home = home or paths.home
    path = ":".join([str(paths.root / "bin"), str(home / ".local" / "bin"), "/opt/homebrew/bin",
                     "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    return {
        "PATH": path,
        "HOME": str(home),
        "KEEL_HOME": str(paths.root),
        # WHICH TOML (c-711): the config this was installed from, when it is not the
        # checkout's own. The gateway reads `[voice.judges]` from it, and every `kb`, `keel`
        # and Harbor turn it starts inherits it, so they open the board the deck shows.
        # Without it they loaded `<root>/keel.toml`, whatever config `install` was run with.
        **config_module.named_env(cfg),
        # WHERE KEEL KEEPS WHAT THE GATEWAY READS OF KEEL'S (c-711): the talker writes its pid
        # under the config's state dir (`keel/talker.py`), which on an install is not
        # `<root>/state`. The gateway's own files do not follow this; see its `KEEL_STATE`.
        "KEEL_STATE_DIR": str(cfg.state_dir),
        "KEEL_SEGMENTS_DIR": str(cfg.segments_dir),
        # WHERE THE DECK ANSWERS, for the digest (decision V16). The gateway builds its
        # board document from `GET http://127.0.0.1:<this>/api/state`, so the deck's port
        # has to arrive the way the gateway's own does: through the service file, out of
        # the config. Without it the gateway falls to `harbor_voice.config`'s 8790
        # default, and a moved deck would quietly cost every turn its provider rows and
        # its second space while still answering confidently.
        "KEEL_SERVE_PORT": str(cfg.serve_port),
        # WHERE AN ADAPTER'S MISHEARINGS LIVE: `hearing` merges each adapter's
        # `hearing.json`, because an employer's name may only be written in its pack.
        "KEEL_ADAPTERS_DIR": str(cfg.adapters_dir),
        "HARBOR_VOICE_PORT": str(cfg.voice_port),
        "HARBOR_VOICE_SPACE_DEFAULT": cfg.voice_space_default,
        "HARBOR_VOICE_MODE_DEFAULT": cfg.voice_mode_default,
        # WHICH SYNTHESISER THE PAGE OPENS WITH (V7, card c-312). The third of the page's
        # defaults to travel this way, for the same reason as the other two: the page is
        # static files that cannot read the config, so the gateway serves the value in
        # /voice/flags.js and this is how the gateway learns it.
        "HARBOR_VOICE_ENGINE_DEFAULT": cfg.voice_engine_default,
        # END OF UTTERANCE AND THE CORPUS (V1, c-311). Both arrive the way every other
        # voice setting does: out of the config, through the service file, into the
        # gateway's environment, because the gateway reads its environment and never
        # parses the config. `vad = "off"` in the config plus `keel voice install` is the
        # whole of the way back to the twenty second backstop.
        "HARBOR_VOICE_VAD": cfg.voice_vad,
        # THE SILENCE THAT ENDS HIS SENTENCE (lane H, H6): 2.0 s, approved on the corpus.
        # Until this key it was only the gateway's own default, so changing it meant editing
        # code; now it is `[voice] vad_hangover` plus `keel voice install --load`.
        "HARBOR_VOICE_VAD_HANGOVER": seconds(cfg.voice_vad_hangover),
        "HARBOR_VOICE_RECORD": "1" if cfg.voice_record else "0",
        # HARBOR'S OWN TURNS KEPT ALIVE AND STREAMED (R2), off unless the config says so.
        "HARBOR_VOICE_HARBOR_KEPT_ALIVE": "1" if cfg.voice_harbor_kept_alive else "0",
        # THE TWO MODEL TURNS THE GATEWAY RUNS (`[models]`, the overnight clearance). A turn
        # given no `--model` runs on the account's own default, so both are pinned here and
        # `harbor_voice.config` holds the same two values for a service file written before.
        "HARBOR_VOICE_CONVERSE_MODEL": cfg.turn_models["converse"],
        "HARBOR_VOICE_REFINE_MODEL": cfg.turn_models["refine"],
        **(LINUX_SPEECH if service_module.platform() == service_module.SYSTEMD else {}),
    }


def service(cfg, paths: Paths, home: Path | None = None, python: str | None = None) -> service_module.Service:
    """The venv's python running the gateway from the repo, restarted whenever it exits,
    logs under state/. `python` falls back to the venv's interpreter, else this one (the
    gateway then serves without a speech model and says so on /voice/health)."""
    python = python or (str(paths.venv_python) if paths.venv_python.exists() else sys.executable)
    return service_module.Service(
        label=LABEL,
        description="Keel voice gateway",
        argv=[python, str(paths.gateway)],
        cwd=paths.root,
        env=environment(cfg, paths, home),
        stdout=paths.log,
        stderr=paths.log,
        throttle=10,
        cpu_weight=VOICE_CPU_WEIGHT,
        # BOTH KEYS THIS GATEWAY MAY NEED, by the same mechanism: the Google TTS key and
        # (V10, c-313) the judges' Jev key. A `LoadCredential=` whose source is missing
        # fails the unit with 243/CREDENTIALS, so `install` leaves an empty 0600 source for
        # each rather than a missing one, and an empty key reads as no key.
        # The credential NAME is what the gateway reads under $CREDENTIALS_DIRECTORY, so
        # it is the file's name and must equal `harbor_voice.config`'s constant for it.
        credentials={KEYS[name][0]: paths.credential_for(name) for name in sorted(KEYS)},
    )


def render_plist(cfg, paths: Paths, home: Path | None = None, python: str | None = None) -> bytes:
    return service_module.plist(service(cfg, paths, home, python))


def install(cfg, paths: Paths, load: bool = False) -> int:
    if not paths.venv_python.exists():
        print("note: no .venv-voice, so the service will run without the speech model; build it with `keel voice venv`")
    if paths.manager.kind == service_module.SYSTEMD and ensure_credential(paths, "jev"):
        print("note: no Jev key, so every judge call is its rule's verdict and a counted "
              f"miss; `keel voice key set --name jev` puts it in {paths.credential_for('jev')}")
    if paths.manager.kind == service_module.SYSTEMD and ensure_credential(paths):
        print(f"note: no Google key, so voice speaks with kokoro-onnx; `keel voice key set` puts it in {paths.credential}")
    (paths.data / "cache").mkdir(parents=True, exist_ok=True)
    for written in paths.manager.write(service(cfg, paths), paths.etc):
        print(f"wrote {written}")
    print(config_module.service_reads(cfg))
    if load:
        return paths.manager.load(service(cfg, paths), paths.etc)
    print("not loaded; `keel voice install --load` when ready")
    return 0


def reload_if_loaded() -> bool:
    """`keel voice install --load` with the config as it is now, when the gateway is loaded:
    how a `[voice]` change saved in Settings reaches it (c-633). Never raises, since its
    caller is the deck's own restart; says what it did on stderr."""
    try:
        cfg = config_module.load(ensure=False)
        paths = paths_from(cfg)
        if not paths.manager.state(LABEL)[0]:
            return False
        install(cfg, paths, load=True)
        return True
    except Exception as error:  # noqa: BLE001 - the restart goes on; the gateway keeps its old values
        print(f"voice: could not reload after a settings change: {error}", file=sys.stderr)
        return False


def uninstall(cfg, paths: Paths) -> int:
    for removed in paths.manager.unload(service(cfg, paths)):
        print(f"stopped and removed {removed} (the copy in {paths.etc} is kept)")
    return 0


# ----- the Google key (Linux) -----

def ensure_credential(paths: Paths, name: str = "google") -> bool:
    """Make the source exist, empty if there is no key yet, and say whether it is empty.

    A LoadCredential= whose source is missing fails the unit with 243/CREDENTIALS, and
    Restart=always would retry that forever. An empty file starts it: the gateway reads an
    empty key as no key, and Google steps aside for kokoro-onnx on /voice/health."""
    source = paths.credential_for(name)
    source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    source.parent.chmod(0o700)
    if not source.exists():
        os.close(os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    return source.stat().st_size == 0


def read_key(stream, label: str = "Google TTS key") -> str:
    """From a pipe as it comes, from a terminal with no echo. Never from argv: an argument
    lands in shell history and in `ps`."""
    if stream.isatty():
        import getpass                                  # noqa: PLC0415 - only a terminal needs it
        return getpass.getpass(f"{label}: ").strip()
    return stream.read().strip()


def key_set(paths: Paths, stream=None, name: str = "google") -> int:
    credential, keychain, label = KEYS[name]
    if paths.manager.kind != service_module.SYSTEMD:
        print(f"on macOS the key is in the login keychain: security add-generic-password -U -s {keychain} -a \"$USER\" -w")
        return 2
    key = read_key(stream or sys.stdin, label)
    if not key or any(ch.isspace() for ch in key):
        print("refused: the key is one word with no spaces, and nothing came in")
        return 1
    ensure_credential(paths, name)
    source = paths.credential_for(name)
    tmp = source.with_name(source.name + ".new")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(key)
    os.replace(tmp, source)
    print(f"wrote {source} (0600)")
    # The unit copies the credential when it STARTS, so the gateway only sees a new key on a
    # restart. That restart is the one thing this verb does to something live, so it says so
    # first, and it refuses to do it for nothing (c-313, his note of 2026-09-20: the verb
    # restarted the live gateway to deliver a key the loaded unit had no LoadCredential= for,
    # which bought nothing and restarted a live service anyway).
    loaded, _ = paths.manager.state(LABEL)
    if not loaded:
        print("voice is not loaded; `keel voice install --load` starts it with the key")
        return 0
    if not unit_loads(paths, credential):
        print(f"NOT restarting voice: the loaded unit has no LoadCredential= for "
              f"{credential!r}, so a restart would not hand the gateway this key.")
        print("`keel voice install --load` writes a unit that carries it, and starts it.")
        return 0
    print(f"restarting voice so it reads the new {label} (it copies credentials at start)")
    ok, how = paths.manager.restart(LABEL)
    print(f"restarted voice ({how})" if ok else f"could not restart voice: {how}")
    return 0 if ok else 1


def unit_loads(paths: Paths, credential: str) -> bool:
    """Whether the unit that is actually LOADED carries this credential.

    The copy in the checkout's `etc/` is what the next install would write, which is not the
    same question: a worktree can render a unit naming a credential the running service has
    never heard of. So this reads the installed file, and a manager with no installed copy
    (launchd, or nothing installed) answers no."""
    installed = paths.manager.installed_dir / f"{LABEL}.service"
    try:
        return f"LoadCredential={credential}:" in installed.read_text()
    except OSError:
        return False


def key_check(paths: Paths, name: str = "google") -> int:
    """Whether the key is where the gateway reads it, and never what it is."""
    credential, keychain, _label = KEYS[name]
    flag = "" if name == "google" else f" --name {name}"
    if paths.manager.kind != service_module.SYSTEMD:
        # Without -w, `security` prints the item's attributes and not the secret.
        done = subprocess.run(["security", "find-generic-password", "-s", keychain],
                              capture_output=True, text=True)
        print(f"login keychain, service {keychain}: {'set' if done.returncode == 0 else 'MISSING'}")
        return 0 if done.returncode == 0 else 1
    source = paths.credential_for(name)
    if not source.exists():
        print(f"{source}: MISSING (keel voice key set{flag})")
        return 1
    mode = source.stat().st_mode & 0o777
    size = source.stat().st_size
    print(f"{source}: {'set' if size else f'EMPTY (keel voice key set{flag})'}, mode {mode:04o}"
          + ("" if mode == 0o600 else "  (want 0600: chmod 600 it)"))
    return 0 if size and mode == 0o600 else 1


# ----- status -----

def loaded_pid(paths: Paths) -> tuple[bool, int | None]:
    """(loaded, pid) from the service manager; pid is None when loaded but not running."""
    return paths.manager.state(LABEL)


def process_command(pid: int) -> str:
    done = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return done.stdout.strip()


def seconds(value) -> str:
    """A number of seconds as the config would write it: 2.0, 1.5, 0.75."""
    text = f"{float(value):g}"
    return text if "." in text or "e" in text else text + ".0"


def hangover_applied(wanted, running) -> bool:
    """Whether the gateway runs the hangover `[voice] vad_hangover` asks for (H6)."""
    try:
        return abs(float(running) - float(wanted)) < 1e-9
    except (TypeError, ValueError):
        return False


def hangover_note(cfg, running) -> str:
    """What `[voice] vad_hangover` says beside what the gateway runs (H6): agreement, or
    the value the config asks for and the one command that makes the gateway take it."""
    if hangover_applied(cfg.voice_vad_hangover, running):
        return " (as configured)"
    return (f", configured {seconds(cfg.voice_vad_hangover)}s "
            f"(keel voice install --load to apply)")


def status_lines(cfg, paths: Paths, loaded: bool, pid: int | None, doc: dict | None) -> list[str]:
    lines = [f"voice: {'loaded' if loaded else 'not loaded'} ({LABEL})" + (f", pid {pid}" if pid else ""),
             # READ WITH `.get`, NOT BY SUBSCRIPT, and the lookup tier is why. This line
             # carried `doc['router']['backend']` and the gateway stopped reporting a
             # router when that tier was deleted, so `keel voice status` raised a KeyError
             # against a perfectly healthy gateway. A status command is what somebody runs
             # when they already suspect something is wrong; it may not be the thing that
             # breaks. `lookupTier` is the honest note the gateway sends in its place.
             "health: " + (f"up {doc['upSeconds']}s on 127.0.0.1:{cfg.voice_port}, "
                           f"stt {doc.get('stt', {}).get('backend', '?')}, "
                           f"tts {doc.get('tts', {}).get('backend', '?')}, "
                           f"lookup tier {doc.get('lookupTier', 'unknown')}"
                           if doc else f"not answering on 127.0.0.1:{cfg.voice_port}")]
    if doc and not doc["stt"].get("ready", False):
        lines.append(f"        {doc['stt'].get('why') or 'the speech model is not ready'}")
    if doc:
        vad = doc.get("vad") or {}
        lines.append("detector: " + (f"{vad.get('backend')}, hangover "
                                     f"{vad.get('hangoverSeconds')}s"
                                     + hangover_note(cfg, vad.get("hangoverSeconds"))
                                     if vad.get("ready") else
                                     f"none, hands-free waits the page out "
                                     f"({vad.get('why') or 'no detector'})"))
        # SAID WHENEVER THERE IS ANYTHING TO SAY, not only while it is recording. A
        # corpus left on disk after the flag went off is exactly the state somebody
        # would want to be reminded of, since it is his voice.
        rec = doc.get("record") or {}
        if rec.get("recording") or rec.get("count"):
            lines.append(f"corpus: {'recording, ' if rec.get('recording') else 'not recording, '}"
                         f"{rec.get('count', 0)} utterances, {rec.get('megabytes', 0)} MB, "
                         f"oldest {rec.get('oldestDays', 0)} days"
                         + ("  (keel voice corpus --delete)" if rec.get("count") else ""))
    if not doc:
        # NOTHING ANSWERING TO SAY WHAT IT RUNS, so what the config asks for (H6).
        lines.append(f"detector: hangover configured {seconds(cfg.voice_vad_hangover)}s")
    if doc and not doc.get("snapshot", {}).get("healthy", True):
        lines.append(f"        board snapshot is {doc['snapshot'].get('ageSeconds')}s old: {doc['snapshot'].get('error')}")
    lines += [f"venv: {paths.venv}" + ("" if paths.venv_python.exists() else "  MISSING (keel voice venv)"),
              f"data: {paths.data}", f"log: {paths.log}"]
    return lines


def status(cfg, paths: Paths) -> int:
    loaded, pid = loaded_pid(paths)
    doc = health(cfg.voice_port)
    for line in status_lines(cfg, paths, loaded, pid, doc):
        print(line)
    if pid:
        print(f"process: {process_command(pid)}")
    return 0 if doc else 1


# ----- the rendered filler and ack audio (c-288) -----

# The count, read by the venv's interpreter because the corpus is the speech package's.
# The filler lines, the capture acks AND the handoff lines, which is what
# `keel-voice-corpus render` renders.
#
# ONE COUNT PER ENGINE THE VOICE CONTROL OFFERS (V7, card c-312). The cache key names the
# engine and the voice, and he picks the engine per session, so "how many clips are there"
# is a question per set: a box with every Google clip rendered and no Kokoro one would
# synthesise every filler live for a whole Kokoro session while reporting 355 of 355.
#
# AND ONE PER SPEAKER INSIDE EACH (V8, card c-316), for the same reason one step further
# in. A connected house speaks in its own voice, so its fixed line is a clip of its own
# under a key of its own; counting only Harbor's sets would report a full cache while the
# house's line was silent, and that is the kind of thing found on the phone rather than in
# a test. `corpus.audio_sets` is the one place the pairs are enumerated, so this and the
# render cannot disagree about what exists.
AUDIO_COUNT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from harbor_voice import corpus
sets = corpus.set_stats()
whole = dict(sets[0])
whole["rendered"] = sum(s["rendered"] for s in sets)
whole["lines"] = sum(s["lines"] for s in sets)
whole["missing"] = sum(s["missing"] for s in sets)
whole["sets"] = sets
print(json.dumps(whole))
"""


def audio_environment(cfg, paths: Paths) -> dict[str, str]:
    """The gateway's own environment, so a clip is keyed to the voice the gateway will ask
    for (the cache key names the voice). On Linux the key is found where the unit's
    LoadCredential= would put it: the source directory holds it under the same name."""
    env = {**os.environ, **environment(cfg, paths)}
    if paths.manager.kind == service_module.SYSTEMD:
        env["CREDENTIALS_DIRECTORY"] = str(paths.credential.parent)
    return env


def audio_count(cfg, paths: Paths) -> dict | None:
    if not paths.venv_python.exists():
        return None
    done = subprocess.run([str(paths.venv_python), "-c", AUDIO_COUNT, str(paths.root / "voice")],
                          env=audio_environment(cfg, paths), capture_output=True, text=True)
    if done.returncode != 0:
        return None
    return json.loads(done.stdout.strip().splitlines()[-1])


def audio(cfg, paths: Paths, render: bool = False) -> int:
    """How much of the corpus has a clip; with `render`, the missing ones rendered first.

    A box that came up without them speaks every filler line through the TTS chain, live,
    at the moment a turn is waiting: the box had 0 of 355 on 2026-09-20. Rendering needs
    the preferred voice's key, and refuses without it rather than fill the cache with clips
    in a voice nothing will ask for (`keel-voice-corpus render` says why).

    ONE SET PER ENGINE THE VOICE CONTROL OFFERS (V7) AND PER SPEAKER INSIDE IT (V8),
    counted and rendered together, and the Google key is needed only for the google sets:
    the local ones render offline. The sets are lopsided on purpose, Harbor's 364 lines
    against a house's one, and each is printed on its own rather than summed into a single
    ratio that would hide a silent house."""
    found = audio_count(cfg, paths)
    if found is None:
        print("cannot count the clips: no .venv-voice (`keel voice venv`), or the corpus does not load")
        return 1
    if render and found["missing"]:
        sets = found.get("sets") or []
        google_short = any(s["engine"] == "google" and s["missing"] for s in sets) or not sets
        if (google_short and paths.manager.kind == service_module.SYSTEMD and not (
                paths.credential.exists() and paths.credential.stat().st_size)):
            print(f"{found['missing']} clips missing, and no Google key to render them with "
                  f"(`keel voice key set` puts it in {paths.credential})")
            return 1
        subprocess.run([str(paths.venv_python), str(paths.root / "bin" / "keel-voice-corpus"), "render"],
                       env=audio_environment(cfg, paths), cwd=paths.root)
        found = audio_count(cfg, paths) or found
    for one in found.get("sets") or []:
        who = f"{one['engine'] or 'preferred'} as {one.get('speaker') or 'harbor'}"
        print(f"  {who}: {one['rendered']}/{one['lines']}"
              + (f", {one['missing']} missing" if one["missing"] else ""))
    print(f"{found['rendered']}/{found['lines']} lines have audio in {found['dir']}"
          + (f", {found['missing']} missing" if found["missing"] else ""))
    return 0 if found["lines"] and not found["missing"] else 1


# ----- parser -----

def corpus(cfg, paths: Paths, delete: bool = False) -> int:
    """The recorded utterances: how many there are, or delete every one of them.

    WHY A VERB RATHER THAN `rm`. This is what the follow-up card runs the moment the two
    numbers are written down, and it is what he runs if he changes his mind halfway
    through the two or three days. A verb is something the Atlas can name and something
    `keel voice status` can point at; a path somebody has to retype correctly is not.

    IT ASKS THE GATEWAY FIRST, so the count is the running process's own, and falls back
    to the directory when nothing is answering. Deleting works either way: the files are
    the truth and the gateway holds no handle on them.
    """
    pcm = paths.data / "pcm"
    doc = health(cfg.voice_port)
    rec = (doc or {}).get("record") or {}
    if delete:
        gone = 0
        for path in sorted(pcm.glob("*.wav")) if pcm.is_dir() else []:
            try:
                path.unlink()
            except OSError:
                continue
            gone += 1
        print(f"deleted {gone} recordings from {pcm}")
        if rec.get("recording"):
            print("still recording: set `record = false` under [voice] in the install's config.toml, "
                  "then `keel voice install` and restart the gateway")
        return 0
    files = sorted(pcm.glob("*.wav")) if pcm.is_dir() else []
    total = sum(f.stat().st_size for f in files) / (1024 * 1024)
    print(f"corpus: {len(files)} utterances, {total:.1f} MB in {pcm}")
    print(f"recording: {'on' if rec.get('recording') else 'off'}"
          + ("" if doc else "  (the gateway is not answering; read from disk)"))
    if files:
        print("measure with: bin/keel-voice-vad-measure")
        print("delete with:  keel voice corpus --delete")
    return 0


# ----- the judges (V10) -----

def judge(cfg, key: str, mode: str) -> int:
    """Set one key's live mode, or `default` to drop the override.

    `on` is refused while the key has no confidence floor. V10 sets no floor until B0's
    number is on the card and a week of the shadow report has been read, and a verb that
    refuses is the mechanism behind that sentence."""
    toml_path = cfg.source or config_module.config_path()
    before = judges_module.effective(toml_path, cfg.state_dir)
    if key not in judges_module.KEYS:
        print(f"refused: {key!r} is not a judge key. They are: "
              + ", ".join(judges_module.KEYS))
        return 1
    if mode == "on" and before[key]["floor"] is None:
        print(f"refused: {key} has no confidence floor, so `on` has no meaning yet.")
        print("V10 sets none until B0's number from this machine is on the card and a week "
              "of the shadow report has been read; `keel voice judges` is that report.")
        print(f"Set one in [voice.judge_floors] in {toml_path} first.")
        return 1
    try:
        judges_module.write_override(cfg.state_dir, key, None if mode == "default" else mode)
    except judges_module.SwitchError as exc:
        print(f"refused: {exc}")
        return 1
    after = judges_module.effective(toml_path, cfg.state_dir)
    if after[key]["mode"] == before[key]["mode"] and after[key]["from"] == before[key]["from"]:
        print(f"unchanged: {judges_module.line(key, after[key])}")
        return 0
    judges_module.log_flip(cfg.state_dir, key, before[key], after[key])
    print(f"{key}: {before[key]['mode']} ({before[key]['from']}) -> "
          f"{after[key]['mode']} ({after[key]['from']})")
    if after[key]["held"]:
        print("held at shadow: the mode asked for was on and the key has no floor")
    print("the gateway reads this on its next turn; no restart and no deploy")
    return 0


def judges(cfg, since: str = "", days: int = 7, labels: list[str] | None = None) -> int:
    """The shadow report, which is the evidence for a flip; with `--since`, the verdict per
    key over that window (c-552, `keel/judgeverdict.py`)."""
    if since:
        return judges_verdict(cfg, since, days, labels or [])
    toml_path = cfg.source or config_module.config_path()
    for said in judges_module.report(toml_path, cfg.state_dir):
        print(said)
    return 0


def judges_verdict(cfg, since: str, days: int, labels: list[str]) -> int:
    """`keel voice judges --since <date>`: flip on, drop or needs more data, per key."""
    try:
        start = date.fromisoformat(since)
    except ValueError:
        print(f"refused: --since takes a date, YYYY-MM-DD, not {since!r}")
        return 1
    paths = [Path(p) for p in labels]
    default = cfg.state_dir / "voice" / judgeverdict.LABELS_FILE
    if default.exists() and default not in paths:
        paths.insert(0, default)
    doc = judgeverdict.verdict(cfg.state_dir, start, days=max(1, days), label_paths=paths,
                               space_of=_card_spaces(cfg),
                               words=judgeverdict.vocabulary(cfg.adapters_dir, *packs.roots(cfg.root)))
    for said in judgeverdict.lines(doc):
        print(said)
    return 0


def _card_spaces(cfg):
    """A card id to its space on this machine's board, "" when it cannot say."""
    from keel.board import Board
    seen: dict[str, str] = {}
    board = None

    def space_of(card: str) -> str:
        nonlocal board
        if card not in seen:
            try:
                board = board or Board(cfg.db_path)
                seen[card] = str(board.get(card).get("space") or "")
            except Exception:                                           # noqa: BLE001
                seen[card] = ""
        return seen[card]
    return space_of


def latency(cfg, paths: Paths, as_json: bool = False, last: int = 0) -> int:
    """Per-stage timing of his real turns, read off the transcript (D-5). Read only."""
    doc = voicelatency.report(paths.data / "transcript.jsonl", last=last)
    if as_json:
        print(json.dumps(doc, indent=1))
        return 0
    print(f"transcript: {doc['transcript']}")
    for line in voicelatency.lines(doc["tiers"]):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel voice", description="the voice gateway's runtime")
    subs = parser.add_subparsers(dest="verb", required=True)
    subs.add_parser("venv")
    sub = subs.add_parser("install")
    sub.add_argument("--load", action="store_true", help="also start it under launchd (macOS) or systemd (Linux)")
    subs.add_parser("uninstall")
    subs.add_parser("status")
    sub = subs.add_parser("key", help="a key this machine holds, on Linux: google or jev")
    sub.add_argument("action", choices=["set", "check"])
    sub.add_argument("--name", choices=sorted(KEYS), default="google",
                     help="which key: google (TTS) or jev (the judges, V10)")
    sub = subs.add_parser("audio", help="the rendered filler and ack clips: count, or --render the missing")
    sub.add_argument("--render", action="store_true", help="render the missing clips in the preferred voice")
    sub = subs.add_parser("corpus", help="the recorded utterances the hangover is measured on")
    sub.add_argument("--delete", action="store_true", help="delete every recording")
    sub = subs.add_parser("judge", help="set one judge key's live mode (V10)")
    sub.add_argument("key", help=", ".join(judges_module.KEYS))
    sub.add_argument("mode", choices=[*judges_module.MODES, "default"])
    sub = subs.add_parser("judges", help="what the shadow log says, per judge key")
    sub.add_argument("--since", default="", metavar="YYYY-MM-DD",
                     help="the verdict per key over a window starting that day (c-552)")
    sub.add_argument("--days", type=int, default=7, help="the window's length (default 7)")
    sub.add_argument("--labels", action="append", default=[], metavar="PATH",
                     help="a labels file beside state/voice/judge-labels.json; repeatable")
    sub = subs.add_parser("latency", help="where a turn's time goes, per stage, from the "
                                          "transcript (read only)")
    sub.add_argument("--json", action="store_true", help="the summary and every turn as JSON")
    sub.add_argument("--last", type=int, default=0, metavar="N", help="only the last N turns")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_module.load()
    paths = paths_from(cfg)
    if args.verb == "venv":
        return build_venv(paths)
    if args.verb == "install":
        return install(cfg, paths, load=args.load)
    if args.verb == "uninstall":
        return uninstall(cfg, paths)
    if args.verb == "key":
        return (key_set(paths, name=args.name) if args.action == "set"
                else key_check(paths, name=args.name))
    if args.verb == "audio":
        return audio(cfg, paths, render=args.render)
    if args.verb == "corpus":
        return corpus(cfg, paths, delete=args.delete)
    if args.verb == "judge":
        return judge(cfg, args.key, args.mode)
    if args.verb == "judges":
        return judges(cfg, since=args.since, days=args.days, labels=args.labels)
    if args.verb == "latency":
        return latency(cfg, paths, as_json=args.json, last=args.last)
    return status(cfg, paths)
