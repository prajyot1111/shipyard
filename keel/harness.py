"""The only module that runs the `claude` binary.

Sessions are started with `claude --bg`, listed with `claude agents --json`, read with
`claude logs`, resumed with `claude --resume <id> --bg` and stopped with `claude stop`.
Two more, both for a connected turn (`keel/converse.py`): `turn` takes ONE headless turn
into a session that is not running (`claude -p --resume`, the answer on stdout), and `wake`
puts a stopped session back in the background with the options it was started with. A turn
is the one call that waits for minutes, so it is the one that runs in its own process group
and is killed as a group when it overruns (`run_alone`); everything else goes through `run`.
`turn_streamed` is that same turn with a reader on its stdout (`stream_alone`), which is
what lets a connected voice turn narrate what the house is doing while it does it (V5).
`open_conversation` is the fourth: ONE process that takes sentence after sentence on its
stdin (`--input-format stream-json`), which is what a connected voice conversation is now
(V12), a third of the latency of a process per sentence and the answer arriving in pieces
while it is written. `keel serve` owns it; `keel/housetalk.py` is the registry.
`login_probe` is the fifth: one `claude -p` of a single word under a space's config dir,
nothing saved, which is how `keel/login.py` learns whether that space's login still works;
it runs in its own group too, so a probe that hangs on the network is killed whole.
`conversation_gone` is the sixth: a `claude -p --resume <id>` with NO prompt and the login
probe's flags, so it can use no tool, in its own group with a 15 second limit, which is how
a resume learns that the harness no longer holds the conversation (c-654).
Every other call goes through `run`, so a test replaces that one name with a fake fed from the
recordings in `tests/fixtures/harness/` and nothing here ever starts a real session.

`start_bg` names the session after the card (`--name <card>`), and that name is what the
child sees as `KEEL_CARD`; the drain counts houses by the same name. `--bg` mints the
session id itself, so the full uuid is looked up in `agents()` after the start.

Two facts from the first live house, both recorded in tests/fixtures/harness/README.md:
`claude agents`, `logs` and `stop` see only the sessions of the `CLAUDE_CONFIG_DIR` they
run under, so every listing here takes the space's config dir; and the variadic flags
(`--disallowed-tools`, `--add-dir`, `--tools`) swallow a positional that follows them, so
the prompt always goes before them.

ANOTHER USER'S CONFIG DIR RUNS AS THAT USER (Bosun as its own Unix user on the box,
docs/atlas/96-bosun.md, "Bosun's own user"). A config dir owned by a user other than this
process's is that user's `claude`: every call builds its argv through `command`, which runs
`sudo -n -u <owner> -H env <what the caller set> <owner's claude> ...`. Only what the caller
added to the environment travels (its config dir, Keel's variables); this process's own
environment, its HOME and PATH included, never does. Nothing names Bosun here: who owns the
directory is the whole rule, and a sudo rule on the box is what lets Keel's user run it.
"""

import concurrent.futures
import functools
import json
import os
import pwd
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

from keel import childenv, config as config_module, models

FALLBACK_BIN = Path("~/.local/bin/claude")
BACKGROUNDED = re.compile(r"backgrounded\s+·\s+([0-9a-f]{8})\s+·\s+(\S.*?)\s*$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>]")
RESOLVE_TRIES = 10
RESOLVE_PAUSE = 0.5


class HarnessError(Exception):
    """`claude` did not do what was asked; the message carries its output."""


def claude_bin() -> str:
    """`claude` from PATH, else `~/.local/bin/claude`."""
    return shutil.which("claude") or str(FALLBACK_BIN.expanduser())


def owner_of(config_dir: str | Path | None) -> pwd.struct_passwd | None:
    """The user who owns `config_dir` when that is not this process's user, else None (and
    None for a directory this process cannot see)."""
    if not config_dir:
        return None
    try:
        uid = Path(config_dir).expanduser().stat().st_uid
    except OSError:
        return None
    if uid == os.getuid():
        return None
    try:
        return pwd.getpwuid(uid)
    except KeyError:
        return None


# The PATH another user's claude runs with: its own bin first, then the system's.
RUN_AS_PATH = "{home}/.local/bin:/usr/local/bin:/usr/bin:/bin"


def command(argv: list[str], env: dict | None,
            cwd=None) -> tuple[list[str], dict | None, str | None]:
    """The full argv, environment and working directory for `claude <argv>`: this user's
    claude, or, when the environment points at a config dir another user owns, that user's
    through sudo. That user runs in `cwd` when it lies in its home, else in its home: it
    cannot enter this user's directories, and sudo keeps the caller's."""
    owner = owner_of((env or {}).get("CLAUDE_CONFIG_DIR"))
    if owner is None:
        return [claude_bin(), *argv], env, cwd
    home = Path(owner.pw_dir)
    where = Path(cwd) if cwd and Path(cwd).is_relative_to(home) else home
    base = os.environ
    carried = {key: value for key, value in (env or {}).items() if base.get(key) != value}
    if Path(carried.get("CLAUDE_CONFIG_DIR", "")) == Path(owner.pw_dir) / ".claude":
        carried.pop("CLAUDE_CONFIG_DIR")        # its own default: reached unset, as ours is
    carried["PATH"] = RUN_AS_PATH.format(home=owner.pw_dir)
    lead = ["sudo", "-n", "-u", owner.pw_name, "-H", "env", "-C", str(where),
            *[f"{key}={value}" for key, value in sorted(carried.items())]]
    return [*lead, str(home / FALLBACK_BIN.relative_to("~")), *argv], None, str(home)


def run(argv: list[str], *, cwd: str | Path | None = None, env: dict | None = None,
        timeout: int = 120, raw: bool = False) -> subprocess.CompletedProcess:
    """Run `claude <argv>` and return the completed process (tests replace this name).
    `raw` decodes the output as it came, with no newline translation: `text=True` turns every
    `\r` into `\n`, and a TUI's log draws with carriage returns (c-605 review)."""
    full, env, cwd = command(argv, env, cwd)
    if raw:
        done = subprocess.run(full, cwd=cwd, env=env, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)
        return subprocess.CompletedProcess(done.args, done.returncode,
                                           done.stdout.decode("utf-8", "replace"),
                                           done.stderr.decode("utf-8", "replace"))
    return subprocess.run(full, cwd=cwd, env=env, capture_output=True,
                          stdin=subprocess.DEVNULL,
                          text=True, errors="replace", timeout=timeout)


def on_path() -> str | None:
    """`claude` as PATH resolves it, or None (the fallback path does not count)."""
    return shutil.which("claude")


def version() -> str:
    """`claude --version`, stripped; raises HarnessError when it fails."""
    try:
        result = run(["--version"], timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        raise HarnessError(f"claude --version: {error}") from error
    if result.returncode != 0:
        raise HarnessError(f"claude --version exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


DEFAULT_CONFIG_DIR = Path.home() / ".claude"


def is_default_config_dir(config_dir: str | Path | None) -> bool:
    """True when `config_dir` is the machine default, which must be reached UNSET.

    Recorded 2026-09-16 on the first real work card: the keychain credential entry is
    keyed by the CLAUDE_CONFIG_DIR setting, so a session launched with the variable set
    to `~/.claude` reads a different entry than one launched with it unset, and finds no
    login there ("Not logged in") while `claude auth status` in a plain shell says
    logged in. The default profile is therefore addressed by leaving the variable out.
    """
    if config_dir is None:
        return True
    return Path(config_dir).expanduser().resolve() == DEFAULT_CONFIG_DIR.resolve()


def point_env(env: dict, config_dir: str | Path | None) -> dict:
    """Set or clear CLAUDE_CONFIG_DIR in `env` so `config_dir` is what claude loads."""
    if is_default_config_dir(config_dir):
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


# NEVER HANDED TO A CLAUDE (c-451, review item 2): `keel/childenv.py` says what and why,
# and every child Keel starts builds its environment there.
WITHHELD = childenv.WITHHELD
own_env = childenv.own_env


def scoped_env(config_dir: str | Path | None) -> dict:
    """The caller's environment pointed at `config_dir` (left as it is for None), always
    without `WITHHELD`."""
    env = own_env()
    return env if config_dir is None else point_env(env, config_dir)


def child_env(card_id: str, config_dir: str | Path) -> dict:
    """The house's environment: its config dir, its card, Keel's root, the house PATH.

    The PATH puts `etc/house-bin` ahead of `bin`, so a house's `open` opens nothing
    (`config.house_path`), and `LAVISH_AXI_NO_OPEN` tells lavish the same thing in its own
    words: probed 2026-09-17, `lavish-axi` honours the variable (and `--no-open`) and
    otherwise spawns the bare name `open`, which the shim then catches. Belt and braces,
    because only one of the two survives a lavish upgrade.
    """
    home = config_module.repo_root()
    env = point_env(own_env(), config_dir)
    env["KEEL_CARD"] = card_id
    env["KEEL_HOME"] = str(home)
    env["PATH"] = config_module.house_path(home, env.get("PATH", ""))
    env["LAVISH_AXI_NO_OPEN"] = "1"
    return env


def session_flags(settings_path: str | Path, *, model=None, add_dirs=(), restricted=False,
                  tools=None, permission_mode="auto", agents: str | None = None,
                  setting_sources: str | None = None) -> list[str]:
    """The flags every house gets, for a start and for a resume alike.

    They come after the prompt on the command line: the variadic ones (`--disallowed-tools`,
    `--add-dir`, `--tools`) would otherwise take a following positional as one more value.

    `--model` is ALWAYS there. Without it `claude` runs on the account's own default, which
    is how c-272 ran five days on Fable (c-434); so no model is refused here, before any
    process is started, rather than left to whatever the config dir would pick.

    `agents` is the `--agents` JSON: the subagents Keel defines for this session, today the
    pipeline's reviewer and verifier (`keel/review/agents.py`). Probed 2026-09-23 on 2.1.280: a `-p`
    session given one with `tools` and `"model": "inherit"` called it by name and returned
    its answer.

    `setting_sources` (c-730) is `--setting-sources`: the settings files the session loads.
    A review card's house runs in a checkout of someone else's code, so it gets `user` alone
    and never the repo's project or local settings and their hooks; `--settings` (Keel's own
    hooks and confinement) applies whatever it says (`claude --help`, 2.1.295).
    """
    if not model:
        raise HarnessError("no model for this house; every house names its model "
                           "(`kb set <id> model=<name>`), never the account's default")
    flags = ["--permission-mode", permission_mode, "--permission-prompts", "none",
             "--settings", str(settings_path), "--model", model]
    if restricted:
        flags.append("--restricted")
    flags += ["--disallowed-tools", "Agent(fork)"]
    for directory in add_dirs:
        flags += ["--add-dir", str(directory)]
    if tools is not None:
        flags += ["--tools", tools if isinstance(tools, str) else ",".join(tools)]
    if agents:
        flags += ["--agents", agents]
    if setting_sources:
        flags += ["--setting-sources", setting_sources]
    return flags


def parse_backgrounded(text: str) -> tuple[str, str]:
    """The `backgrounded · <id> · <name>` line -> (short id, name)."""
    for line in strip_ansi(text).splitlines():
        match = BACKGROUNDED.search(line)
        if match:
            return match.group(1), match.group(2)
    raise HarnessError(f"no `backgrounded · <id> · <name>` line in:\n{text.strip()}")


def _launch(argv: list[str], name: str, *, cwd, config_dir, env: dict | None = None) -> dict:
    """`env` replaces the house's own (`child_env`) for a session that is not a card's:
    Bosun's (`keel/console.py`) must not carry a `KEEL_CARD`."""
    result = run(argv, cwd=str(cwd), env=env if env is not None else child_env(name, config_dir))
    if result.returncode != 0:
        raise HarnessError(f"claude exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    bg_id, _ = parse_backgrounded(result.stdout + "\n" + result.stderr)
    return {"bg_id": bg_id, "session_id": resolve_session(name, bg_id, config_dir)}


def remote_flags(name: str, remote_control: bool) -> list[str]:
    """`--remote-control <name>`: the session is also reachable from the Claude app.

    Probed 2026-09-17: a `--bg` session started this way is listed by `claude agents` as an
    ordinary background session, its hooks fire, a message typed in the app runs in the
    same session, and its log prints the `claude.ai/code/session_...` link (`remote_link`).
    The name is always given explicitly: the flag takes an optional value, so a bare
    `--remote-control` would swallow the prompt as the name. Attaching an existing `--bg`
    session afterwards with `claude remote-control --session-id` does not work: that id is
    looked up on the server, so it only reattaches sessions that already exist remotely.
    """
    return ["--remote-control", name] if remote_control else []


def start_bg(cwd, prompt, *, name, config_dir, settings_path, model=None, add_dirs=(),
             restricted=False, tools=None, permission_mode="auto", remote_control=True,
             agents: str | None = None, env: dict | None = None,
             setting_sources: str | None = None) -> dict:
    """Start a background house for the card `name` in `cwd`; returns bg_id and session_id."""
    argv = ["--bg", "--name", name, *remote_flags(name, remote_control), prompt, *session_flags(
        settings_path, model=model, add_dirs=add_dirs, restricted=restricted, tools=tools,
        permission_mode=permission_mode, agents=agents, setting_sources=setting_sources)]
    return _launch(argv, name, cwd=cwd, config_dir=config_dir, env=env)


def resume_bg(session_id, prompt, *, cwd, config_dir, settings_path, name=None, model=None,
              add_dirs=(), restricted=False, tools=None, permission_mode="auto",
              remote_control=True, agents: str | None = None, env: dict | None = None,
              setting_sources: str | None = None) -> dict:
    """Continue an exited session in the background with the same flags as `start_bg`.

    A resume mints a new session uuid AND a new app link (probed 2026-09-17), so the caller
    re-reads `remote_link` after every resume."""
    argv = ["--resume", session_id, "--bg"]
    if name:
        argv += ["--name", name, *remote_flags(name, remote_control)]
    argv.append(prompt)
    argv += session_flags(settings_path, model=model, add_dirs=add_dirs, restricted=restricted,
                          tools=tools, permission_mode=permission_mode, agents=agents,
                          setting_sources=setting_sources)
    return _launch(argv, name or session_id, cwd=cwd, config_dir=config_dir, env=env)


# c-654. The harness keeps a transcript for its retention period only (30 days by default),
# and three shipping houses last used 32 or more days before were resumed after it on
# 2026-10-05 (c-015, c-017, c-037): `claude --resume <id> --bg` printed its `backgrounded`
# line with the SAME id, exited 0, and the session ended four seconds later with no turn
# (a SessionEnd hook, reason `other`; `claude agents --json --all` lists it `failed`, the
# plain listing not at all). So the launch cannot say it. This can, probed that day on
# 2.1.289 (`tests/fixtures/harness/README.md`): `claude -p --resume <id>` with NO prompt
# exits 1, saying `No conversation found with session ID: <id>` for a conversation that is
# gone and `No deferred tool marker found in the resumed session ... Provide a prompt to
# continue the conversation` for one that is there (about 1.6 s, no model call).
#
# The probe is made UNABLE TO ACT (c-654 review): a session that ended on a deferred tool
# call was not probed, and its message says the harness would look for one to continue
# from. So it carries the login probe's flags (`LOGIN_FLAGS`: no tool, no MCP server,
# nothing saved, the cheapest model), runs in its own process group with a short limit
# (`run_alone`: a `claude` that hangs is killed whole, never left holding the card's lock),
# and the caller asks it only of a session the harness lists no live process for
# (`keel/afresh.py`). A short id is no session id to `-p --resume` (it answers "is not a
# UUID and does not match any session title", probed), so it is resolved to its uuid
# through the full listing first, and one that listing does not hold is never asked.
NO_CONVERSATION = "No conversation found with session ID"
GONE_SECONDS = 15
SESSION_UUID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


def full_session(session_id, config_dir) -> str | None:
    """The session's uuid: itself, or for the short id a card kept because the listing never
    showed its row (`resolve_session`), the uuid `claude agents --json --all` gives it now.
    None when nothing says which session a short id is."""
    session_id = str(session_id or "")
    if SESSION_UUID.match(session_id):
        return session_id
    row = find(session_id, agents(config_dir, all_sessions=True)) if session_id else None
    found = str((row or {}).get("sessionId") or "")
    return found if SESSION_UUID.match(found) else None


def conversation_gone(session_id, *, cwd, config_dir) -> bool:
    """True only when the harness SAYS it holds no conversation for this session, so a
    resume of it could only fail. Anything else (a conversation that is there, a session
    running, a login that expired, a probe that overran or could not run, a short id
    nothing resolves) is False: never a guess, and the resume then says what it says."""
    full = full_session(session_id, config_dir)
    if full is None:
        return False
    try:
        result = run_alone(["-p", "--resume", full, *LOGIN_FLAGS], cwd=str(cwd),
                           env=scoped_env(config_dir), timeout=GONE_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode != 0 and NO_CONVERSATION in f"{result.stderr}\n{result.stdout}"


# A connected turn's own numbers, measured on the box on 2026-09-20 against Claude Code
# 2.1.278 (card c-315, the scripts and logs in `state/cards/c-315/probe/`): `claude stop`
# 0.8s, the headless turn 5.0s on a 237 KB transcript and 6.7s on an 889 KB one (the model's
# own answer is most of that, and every `-p --resume` re-reads the whole transcript), the
# wake 0.9s. So Keel's own overhead is under two seconds, and none of it repeats between the
# turns of one conversation, because the house is held down for the whole of it.
TURN_TIMEOUT = 300
# What `-p` is asked for, so the answer comes back as a field and not as prose to scrape.
TURN_FORMAT = ("--output-format", "json")
# `claude -p --resume` while the session's background process is ALIVE is refused with this
# in the message (probed 2026-09-18 and again 2026-09-20). It is the reason a connected turn
# stops the process first, and it is recognised here so the caller can say something better
# than the CLI's own sentence.
RUNNING_REFUSAL = "is running as a background session"


# How long the whole group gets between its SIGTERM and its SIGKILL, and how often the
# group is checked in between. The same shape `bin/keel-browser` uses, and for the same
# reason: killing the leader alone leaves its children running.
GROUP_GRACE = 2.0
GROUP_POLL = 0.1


def kill_group(proc: subprocess.Popen) -> None:
    """End the whole process group `proc` leads: SIGTERM, a couple of seconds, SIGKILL.

    `subprocess.run(timeout=...)` kills the child it started and NOTHING the child started,
    so a wedged turn would leave a `claude` and whatever it spawned behind. On a 12 GB box
    that is the voice gateway's memory. The group is this process's own (`start_new_session`),
    so nothing outside the turn can be in it.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        return
    for sig, grace in ((signal.SIGTERM, GROUP_GRACE), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, OSError):
                return                       # the whole group is gone, not just the leader
            time.sleep(GROUP_POLL)


def run_alone(argv: list[str], *, cwd=None, env=None,
              timeout: int = TURN_TIMEOUT) -> subprocess.CompletedProcess:
    """`claude <argv>` in its OWN process group, killed as a group if it overruns.

    The one call here that does not go through `run`, and the docstring above says why: a
    turn is the only thing Keel waits on for minutes, so it is the only one that can wedge
    with children. Tests replace this name the way they replace `run`.
    """
    full, env, cwd = command(argv, env, cwd)
    proc = subprocess.Popen(full, cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, errors="replace",
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        try:
            out, err = proc.communicate(timeout=GROUP_GRACE)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        raise subprocess.TimeoutExpired(argv, timeout, output=out, stderr=err) from None
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


# The login probe (`keel/login.py`): one word asked of the cheapest model, nothing saved,
# no MCP server and no tool started, so all it can prove is that the login answers.
LOGIN_PROMPT = "Reply with the single word ok."
LOGIN_FLAGS = ("--no-session-persistence", "--model", models.LOGIN_MODEL, "--strict-mcp-config",
               "--tools", "")


def login_probe(config_dir, *, cwd, timeout: int) -> subprocess.CompletedProcess:
    """`claude -p` under `config_dir` in its own process group, with the space's
    environment and never his token (`scoped_env`). Raises TimeoutExpired on an overrun,
    after the group is killed. The prompt goes before `--tools`, which is variadic."""
    return run_alone(["-p", LOGIN_PROMPT, *LOGIN_FLAGS], cwd=cwd, env=scoped_env(config_dir),
                     timeout=timeout)


# How long the readers get to finish after the group is gone. They are reading a pipe whose
# writer has been killed, so this is the time for an EOF to arrive, not for work to finish.
READER_JOIN = 2.0


def stream_alone(argv: list[str], *, cwd=None, env=None, timeout: int = TURN_TIMEOUT,
                 on_line=None) -> subprocess.CompletedProcess:
    """`run_alone` with its stdout read a line at a time, AS the lines arrive.

    Same process group and same group kill: a streamed turn is the same turn with a reader
    on the other end of the pipe, so nothing `run_alone` guarantees may be given up for it.
    What is added is that stdout is consumed by a thread instead of by `communicate`, which
    is what makes a line usable before the turn has finished.

    TWO PIPES NEED TWO READERS. `communicate` exists because a process that fills the pipe
    nobody is draining blocks forever, and reading stdout by hand puts stderr in exactly
    that position. So stderr gets a reader of its own, and neither of them is the thread
    that waits.

    `on_line` NEVER STOPS THE TURN. It runs on the reader thread, inside the turn that is
    answering him, so it is called under a guard: a listener that raises is logged onto the
    result and the turn carries on, because a narration that failed is a quieter wait and
    never a lost answer.
    """
    full, env, cwd = command(argv, env, cwd)
    proc = subprocess.Popen(full, cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, errors="replace",
                            bufsize=1, start_new_session=True)
    out: list[str] = []
    err: list[str] = []

    def drain(stream, sink, listener):
        try:
            for line in stream:
                sink.append(line)
                if listener is not None:
                    try:
                        listener(line)
                    except Exception:                                   # noqa: BLE001
                        pass
        except (ValueError, OSError):
            pass                              # the pipe went with the group; EOF by force
        finally:
            try:
                stream.close()
            except (ValueError, OSError):
                pass

    readers = [threading.Thread(target=drain, args=(proc.stdout, out, on_line),
                                name="turn-stdout", daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, err, None),
                                name="turn-stderr", daemon=True)]
    for reader in readers:
        reader.start()

    def collect():
        for reader in readers:
            reader.join(timeout=READER_JOIN)
        return "".join(out), "".join(err)

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        try:
            proc.wait(timeout=GROUP_GRACE)
        except subprocess.TimeoutExpired:
            pass
        heard, said = collect()
        raise subprocess.TimeoutExpired(argv, timeout, output=heard, stderr=said) from None
    heard, said = collect()
    return subprocess.CompletedProcess(argv, proc.returncode, heard, said)


# WHAT A STREAMED TURN IS ASKED FOR. `--verbose` is not optional: `stream-json` is refused
# without it. The records are the ones recorded in `state/cards/c-317/probe/README.md`.
TURN_STREAM_FORMAT = ("--output-format", "stream-json", "--verbose")


def turn_streamed(session_id: str, prompt: str, *, cwd, config_dir, settings_path,
                  model=None, add_dirs=(), restricted=False, tools=None,
                  permission_mode="auto", timeout: int = TURN_TIMEOUT,
                  on_record=None, setting_sources: str | None = None) -> dict:
    """`turn`, with every record handed to `on_record` as it arrives (V5).

    THE ANSWER IS THE SAME OBJECT EITHER WAY. The last record a streamed turn writes is
    `{"type": "result", "result": ...}`, which is byte for byte what `--output-format json`
    returns as its whole output (probed 2026-09-20 against Claude Code 2.1.278). So this
    returns the same payload `turn` does and `turn_answer` reads it unchanged: streaming
    adds records BEFORE the one the rest of Keel already understands, it does not replace it.

    `on_record` is called with each decoded record on the reader thread, under the guard in
    `stream_alone`: it narrates, and narration is never worth a turn.
    """
    payload: dict = {}

    def on_line(line: str) -> None:
        text = line.strip()
        if not text:
            return
        try:
            record = json.loads(text)
        except ValueError:
            return                            # a line that is not a record is not an error
        if not isinstance(record, dict):
            return
        if record.get("type") == "result":
            payload.clear()
            payload.update(record)
        elif on_record is not None:
            on_record(record)

    argv = ["-p", "--resume", session_id, *TURN_STREAM_FORMAT, prompt, *session_flags(
        settings_path, model=model, add_dirs=add_dirs, restricted=restricted, tools=tools,
        permission_mode=permission_mode, setting_sources=setting_sources)]
    try:
        result = stream_alone(argv, cwd=str(cwd), env=scoped_env(config_dir),
                              timeout=timeout, on_line=on_line)
    except subprocess.TimeoutExpired as error:
        raise HarnessError(f"the turn took longer than {timeout}s, and it was ended") from error
    if result.returncode != 0 and not payload:
        said = strip_ansi(result.stderr or result.stdout or "").strip().splitlines()
        raise HarnessError(said[-1] if said else f"the turn exited {result.returncode}")
    if not payload:
        raise HarnessError("the turn streamed no result record")
    if payload.get("is_error"):
        raise HarnessError(str(payload.get("result") or "the turn errored"))
    return payload


def turn(session_id: str, prompt: str, *, cwd, config_dir, settings_path, model=None,
         add_dirs=(), restricted=False, tools=None, permission_mode="auto",
         timeout: int = TURN_TIMEOUT, setting_sources: str | None = None) -> dict:
    """One headless turn into `session_id`, synchronously; the decoded `-p --output-format
    json` payload, whose `result` is the answer.

    The session's own background process must be STOPPED first (`RUNNING_REFUSAL`): the two
    doors, a live process and a headless turn, are exclusive in time. The turn continues the
    transcript in place under the same uuid, so the card keeps its session, its app link and
    its history, and the card's own settings file is passed so its hooks fire exactly as they
    do for any other turn (they do fire: probed 2026-09-20, which is why both Stop bodies
    have to recognise a held card).
    """
    argv = ["-p", "--resume", session_id, *TURN_FORMAT, prompt, *session_flags(
        settings_path, model=model, add_dirs=add_dirs, restricted=restricted, tools=tools,
        permission_mode=permission_mode, setting_sources=setting_sources)]
    try:
        result = run_alone(argv, cwd=str(cwd), env=scoped_env(config_dir), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise HarnessError(f"the turn took longer than {timeout}s, and it was ended") from error
    if result.returncode != 0:
        said = strip_ansi(result.stderr or result.stdout or "").strip().splitlines()
        raise HarnessError(said[-1] if said else f"the turn exited {result.returncode}")
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError as error:
        raise HarnessError(f"the turn answered something that is not JSON: {error}") from error
    if payload.get("is_error"):
        raise HarnessError(str(payload.get("result") or "the turn errored"))
    return payload


def turn_answer(payload: dict) -> str:
    """The one spoken line out of a turn's payload, whitespace collapsed."""
    return " ".join(str(payload.get("result") or "").split())


# ----- one process, many sentences (V12) -----

# WHAT A KEPT-ALIVE CONVERSATION IS ASKED FOR, measured on 2026-09-20 against Claude Code
# 2.1.278 on the Mac (the probe is `docs/probes/conversation-probe.py`). One
# `claude -p --resume <id>` per sentence costs 3.6 to 4.1 s to the first token, almost all
# of it start-up and a re-read of the whole transcript. ONE process with `--input-format
# stream-json` on its stdin costs 1.0 to 1.5 s for the same first token, on the same session
# id, with one `result` record per sentence and a clean exit 0 when stdin is closed. So the
# process is kept, and every sentence after the first pays nothing for the start.
#
# `--verbose` is not optional (`stream-json` is refused without it), and
# `--include-partial-messages` is what turns the answer into `content_block_delta` records
# while it is being written, which is what lets the first sentence be SPOKEN before the last
# one exists (`keel/sentences.py`).
CONVERSE_FORMAT = ("--input-format", "stream-json", "--output-format", "stream-json",
                   "--verbose", "--include-partial-messages")
# How long `close` waits for a process whose stdin it has just shut. The probe's exit was
# immediate; past this the group is killed, because a conversation nobody is in must never
# outlive the server that owned it.
CLOSE_GRACE = 5.0
# How long the reader is given to notice the end of the stream. Same reason as READER_JOIN.
QUEUE_TICK = 0.2


def user_line(text: str) -> str:
    """One sentence, in the shape `--input-format stream-json` reads (probed 2026-09-20)."""
    return json.dumps({"type": "user",
                       "message": {"role": "user",
                                   "content": [{"type": "text", "text": str(text)}]}}) + "\n"


def stream_text(record: dict) -> str:
    """The words a `stream_event` record adds to the answer, or "".

    ONLY `text_delta`. A thinking block and a tool call's arguments arrive as deltas of
    their own, and either one spoken out loud would be both nonsense and a leak: the tool
    input is where the file paths are.
    """
    if not isinstance(record, dict) or record.get("type") != "stream_event":
        return ""
    event = record.get("event") or {}
    if event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta") or {}
    return str(delta.get("text") or "") if delta.get("type") == "text_delta" else ""


def _shut(stream) -> None:
    """Close a pipe handle without ever making that the caller's problem."""
    try:
        if stream is not None:
            stream.close()
    except (ValueError, OSError):
        pass


def popen_alone(argv: list[str], *, cwd=None, env=None) -> subprocess.Popen:
    """`claude <argv>` as a long-lived process with its stdin OPEN, in its own group.

    The one place a conversation's process is started, so a test replaces this name the
    way it replaces `run` and `stream_alone` and nothing here ever runs the real binary.
    `start_new_session` is the same guarantee `run_alone` and `stream_alone` give: what is
    killed is the group, never the leader alone.
    """
    full, env, cwd = command(argv, env, cwd)
    return subprocess.Popen(full, cwd=cwd, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, errors="replace",
                            bufsize=1, start_new_session=True)


class Conversation:
    """One `claude` process that takes sentence after sentence into the same session.

    THE OBJECT IS THE PROCESS, and it is owned by whatever is long-lived enough to own a
    process: `keel serve`, through `keel/housetalk.py`. A CLI run once per sentence cannot
    own one, which is why the kept-alive path goes through the server and the one-shot
    `turn` stays exactly where it was for everyone else.

    ONE TURN AT A TIME, AND IT IS THE CALLER'S LOCK. `say` writes one sentence and reads
    until that sentence's `result`, so two threads calling it at once would each read the
    other's records. The session manager holds one lock per card, which is also what makes
    "one conversation per card" true.

    A DEAD CONVERSATION IS NEVER REUSED. A process that exits, a pipe that breaks and a
    turn that overruns all raise `HarnessError` and leave `alive` false; the caller opens a
    new one or falls back to the one-shot turn. Reusing a half-read stream would answer the
    next sentence with the tail of the last one.
    """

    def __init__(self, proc: subprocess.Popen, session_id: str = "",
                 timeout: int = TURN_TIMEOUT):
        self.proc = proc
        self.session_id = session_id
        self.timeout = timeout
        self.opened = time.time()
        self.last_said = time.time()
        self.turns = 0
        self.dead = False
        self.records: "queue.Queue" = queue.Queue()
        self.errors: list[str] = []
        self.readers = [
            threading.Thread(target=self._read_out, name="talk-stdout", daemon=True),
            threading.Thread(target=self._read_err, name="talk-stderr", daemon=True)]
        for reader in self.readers:
            reader.start()

    # -- the two pipes ---------------------------------------------------- #

    def _read_out(self) -> None:
        """Decode stdout onto the queue; None at the end, whatever ended it."""
        try:
            for line in self.proc.stdout:
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except ValueError:
                    continue              # a line that is not a record is not an error
                if isinstance(record, dict):
                    self.records.put(record)
        except (ValueError, OSError):
            pass
        finally:
            _shut(self.proc.stdout)
            self.records.put(None)

    def _read_err(self) -> None:
        """STDERR NEEDS ITS OWN READER, for the reason `stream_alone` gives: a process
        that fills a pipe nobody drains blocks forever, and this one is meant to live for
        a whole conversation. What it says is kept for the message of a failure."""
        try:
            for line in self.proc.stderr:
                self.errors.append(line)
                del self.errors[:-40]
        except (ValueError, OSError):
            pass
        finally:
            _shut(self.proc.stderr)

    # -- the conversation ------------------------------------------------- #

    @property
    def alive(self) -> bool:
        return not self.dead and self.proc.poll() is None

    def _die(self, why: str) -> HarnessError:
        self.dead = True
        kill_group(self.proc)
        said = strip_ansi("".join(self.errors)).strip().splitlines()
        return HarnessError(f"{why}: {said[-1]}" if said else why)

    def say(self, text: str, *, on_record=None, timeout: int | None = None,
            on_written=None) -> dict:
        """One sentence in, that sentence's `result` payload out.

        The payload is what `turn` returns and what `turn_answer` reads, unchanged: a
        kept-alive turn adds records BEFORE the one the rest of Keel already understands,
        exactly as `turn_streamed` does, so nothing downstream has to know which shape ran.

        `on_record` gets every record before the result, on THIS thread, under a guard: it
        narrates and it cuts the answer into sentences, and neither is ever worth a turn.

        `on_written` IS CALLED THE MOMENT THE SENTENCE IS IN THE PIPE, and it is the only
        way the caller can know that. Everything about not asking the house the same
        question twice turns on that one fact: a sentence that was never written may be
        asked again and one that was may not, and only this method can tell them apart.
        """
        if not self.alive:
            raise HarnessError("that conversation's process is gone")
        wait = self.timeout if timeout is None else timeout
        try:
            self.proc.stdin.write(user_line(text))
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as error:
            raise self._die(f"the conversation would not take the sentence: {error}") from None
        if on_written is not None:
            try:
                on_written()
            except Exception:                                           # noqa: BLE001
                pass
        self.last_said = time.time()
        deadline = time.time() + wait
        while True:
            try:
                record = self.records.get(timeout=max(0.0, min(QUEUE_TICK,
                                                               deadline - time.time())))
            except queue.Empty:
                if time.time() >= deadline:
                    raise self._die(f"the turn took longer than {wait}s, and it was ended")
                continue
            if record is None:
                raise self._die("the conversation's process ended mid-turn")
            if record.get("type") == "result":
                self.turns += 1
                self.last_said = time.time()
                if record.get("is_error"):
                    raise HarnessError(str(record.get("result") or "the turn errored"))
                return record
            if on_record is not None:
                try:
                    on_record(record)
                except Exception:                                       # noqa: BLE001
                    pass

    def close(self, timeout: float = CLOSE_GRACE) -> None:
        """Close stdin, wait, then kill the group if it lingers. Never raises.

        CLOSING STDIN IS THE ORDINARY END (probed 2026-09-20: exit 0), and it is also what
        happens by itself when the server that owns this process exits, which is why a
        restart of `keel serve` leaves no orphan. The group kill is the backstop for a
        process that is mid tool-call and not reading its stdin at all.
        """
        self.dead = True
        _shut(self.proc.stdin)
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(self.proc)
            try:
                self.proc.wait(timeout=GROUP_GRACE)
            except subprocess.TimeoutExpired:
                pass
        for reader in self.readers:
            reader.join(timeout=READER_JOIN)
        for stream in (self.proc.stdout, self.proc.stderr):
            _shut(stream)


def open_conversation(session_id: str, *, cwd, config_dir, settings_path, model=None,
                      add_dirs=(), restricted=False, tools=None, permission_mode="auto",
                      timeout: int = TURN_TIMEOUT, env: dict | None = None,
                      setting_sources: str | None = None) -> Conversation:
    """Start one kept-alive conversation into `session_id`, with the card's own flags.

    The same flags a one-shot `turn` passes, for the same reason: this IS that turn, taken
    many times down one pipe, so the hooks, the model, the settings file, the confinement
    and the add-dirs must be identical or the two doors would behave differently. The
    session's background process must be STOPPED first, exactly as for `turn`.

    `env` replaces the scoped one for a session that is not a card's: Bosun's (c-523) carries
    its key, so its `kb` is still `bosun` while he talks to it by voice.
    """
    argv = ["-p", "--resume", session_id, *CONVERSE_FORMAT, *session_flags(
        settings_path, model=model, add_dirs=add_dirs, restricted=restricted, tools=tools,
        permission_mode=permission_mode, setting_sources=setting_sources)]
    try:
        proc = popen_alone(argv, cwd=str(cwd), env=env if env is not None else scoped_env(config_dir))
    except OSError as error:
        raise HarnessError(f"the conversation would not start: {error}") from None
    return Conversation(proc, session_id=session_id, timeout=timeout)


def wake(session_id: str, *, cwd, config_dir, name: str | None = None,
         env: dict | None = None) -> dict:
    """Put a stopped session back in the background, with NO flags and NO prompt.

    Probed 2026-09-20 on 2.1.278: `claude --resume <id> --bg` alone answers "woke session
    <id> with its saved options (--name, --remote-control, --permission-mode,
    --permission-prompts, --settings, --disallowed-tools, --model)" and keeps the SAME
    session id and the SAME claude.ai link. Passing any flag instead starts a COPY under a
    new id, which is what `resume_bg` does on purpose and what the 2026-09-18 probe saw. No
    prompt means no model turn, so waking a house costs nothing but the process.

    The caller checks the id it got back: a build of `claude` that does not keep saved
    options answers with a new one, and then this was a resume in all but name and the card
    has to record it (`house.wake`).

    Probed again 2026-09-26 on 2.1.283 for Bosun's voice hold (c-523,
    `state/cards/c-523/probe/`): stop, one headless turn, then this, on a `--remote-control`
    session: the same id, and the log says remote control is active at the SAME link. `env`
    replaces the house's own for a session that is not a card's (Bosun must never carry a
    `KEEL_CARD`).
    """
    result = run(["--resume", session_id, "--bg"], cwd=str(cwd),
                 env=env if env is not None else child_env(name or session_id, config_dir))
    if result.returncode != 0:
        raise HarnessError(f"claude exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    bg_id, _ = parse_backgrounded(result.stdout + "\n" + result.stderr)
    woken = session_id if session_id.startswith(bg_id) else resolve_session(
        name or session_id, bg_id, config_dir)
    return {"bg_id": bg_id, "session_id": woken}


def resolve_session(name: str, bg_id: str, config_dir=None, tries: int = RESOLVE_TRIES) -> str:
    """The full session uuid for the house named `name`, polled from `agents(config_dir)`.

    The short id is the uuid's first eight characters. When the listing never shows the
    row, the short id is returned so the card still names the session it has.
    """
    for attempt in range(tries):
        for row in agents(config_dir):
            if row.get("name") == name and row.get("kind") == "background":
                session_id = row.get("sessionId") or ""
                if session_id.startswith(bg_id) or row.get("id") == bg_id:
                    return session_id or bg_id
        if attempt + 1 < tries:
            time.sleep(RESOLVE_PAUSE)
    return bg_id


def agents(config_dir=None, all_sessions: bool = False, strict: bool = False) -> list[dict]:
    """`claude agents --json` under `config_dir`; an empty list when the command fails, or
    with `strict` a HarnessError, for a caller that must not read a failed listing as
    "nothing is running" (Bosun's Start, `keel/console.py`)."""
    argv = ["agents", "--json"] + (["--all"] if all_sessions else [])
    result = run(argv, env=scoped_env(config_dir))
    if result.returncode != 0:
        if strict:
            raise HarnessError(f"claude agents exited {result.returncode}:\n{result.stderr}")
        return []
    try:
        rows = json.loads(result.stdout or "[]")
    except ValueError:
        if strict:
            raise HarnessError("claude agents answered something that is not JSON") from None
        return []
    if not isinstance(rows, list):
        if strict:
            raise HarnessError("claude agents answered something that is not a list")
        return []
    return rows


def agents_across(config_dirs, strict: bool = False) -> list[dict]:
    """The union of `agents()` over the spaces' config dirs, one row per session.

    The listings run side by side, each a `claude agents` of about a quarter second, and
    are read back in the dirs' order, so the union is the same as it was one after the
    other: the deck's cold build waits for the slowest rather than their sum (c-540).
    `strict` raises on a listing that failed rather than reading it as no session: the
    deck's kept listing keeps its last good one instead (c-638)."""
    dirs = list(dict.fromkeys(str(directory) for directory in config_dirs))
    one = functools.partial(agents, strict=strict)
    if len(dirs) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(dirs)) as pool:
            listings = list(pool.map(one, dirs))
    else:
        listings = [one(directory) for directory in dirs]
    seen, rows = set(), []
    for listing in listings:
        for row in listing:
            key = row.get("sessionId") or (row.get("kind"), row.get("pid"))
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def find(session_id: str, rows: list[dict] | None = None) -> dict | None:
    """The `agents()` row carrying `session_id` (full uuid or the short id), else None."""
    if not session_id:
        return None
    for row in agents() if rows is None else rows:
        candidate = row.get("sessionId") or ""
        if candidate == session_id or row.get("id") == session_id or (
                len(session_id) == 8 and candidate.startswith(session_id)):
            return row
    return None


# A cursor move forward (`ESC [ n C`) is how the TUI draws a run of spaces; stripped with the
# rest it glued the words together ("Aprove outcome doethat", c-601), so it becomes n spaces.
CURSOR_FORWARD = re.compile(r"\x1b\[(\d*)C")


def strip_ansi(text: str) -> str:
    spaced = CURSOR_FORWARD.sub(lambda m: " " * int(m.group(1) or 1), text)
    return ANSI.sub("", spaced).replace("\r", "")


REMOTE_LINK = re.compile(r"https://claude\.ai/code/(session_[A-Za-z0-9]+)")


def remote_link(bg_id: str, config_dir=None) -> str | None:
    """The newest `claude.ai/code/session_...` link in the session's log, or None.

    The log prints it a few seconds after start (`/remote-control is active · Continue
    here, on your phone, or at <url>`); a caller polls this until it is not None."""
    found = REMOTE_LINK.findall(logs(bg_id, config_dir))
    return f"https://claude.ai/code/{found[-1]}" if found else None


# WHAT THE LOG IS: THE TUI'S SCREEN, DRAWN BY CURSOR MOVES (c-604). Its redraw writes only
# the cells that changed and jumps over the rest (`ESC [ n G` to a column, `ESC [ r ; c H` to a
# cell, `C`/`D`/`A`/`B` by steps), so a stripped log read "Writing held-tap t st in test" with
# the spaces and the unchanged letters gone. `screen` replays the moves onto a grid instead;
# a cell never written is a space.
SCREEN_TOKEN = re.compile(r"\x1b\[([0-9;?<=>:]*)[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
                          r"|\x1bP.*?(?:\x1b\\|$)|\x1b[()][A-Z0-9]|\x1b[=>78DEM]|[\r\n\b\t]"
                          r"|[^\x1b\r\n\b\t]+|\x1b", re.S)
# WHAT A CARRIAGE RETURN IS IN THAT LOG (c-605 review): the TUI returns to column 0 with `\r`
# and makes its own row move after it (`ESC [ 1 B`). `claude logs` hands those back as they
# are; read with newline translation (`text=True`) each became a line feed, every line slid
# one row further down per redraw, and the spinner's letters and counters landed inside
# finished lines ("one-line1docstring2on9all_reports"). So `logs` reads it `raw`.
# A tap never replays megabytes: only the log's last this many characters are drawn.
SCREEN_TAIL = 256 * 1024


def _numbers(params: str, default: int = 1) -> list[int]:
    out = []
    for part in params.lstrip("?<=>").split(";"):
        part = part.split(":")[0]
        out.append(int(part) if part.isdigit() else default)
    return out


def screen(text: str) -> str:
    """The text a terminal would show after `text`, row by row; SGR, titles and modes are
    dropped. Rows are never clipped: the grid grows as far down as it is written."""
    rows: dict[int, dict[int, str]] = {}
    row = col = 0
    text = text[-SCREEN_TAIL:]
    for match in SCREEN_TOKEN.finditer(text):
        token, final = match.group(0), match.group(2)
        if final:
            params = match.group(1) or ""
            n = _numbers(params)[0]
            if final == "C":
                col += n
            elif final == "D":
                col = max(0, col - n)
            elif final == "B":
                row += n
            elif final == "A":
                row = max(0, row - n)
            elif final == "G":
                col = max(0, n - 1)
            elif final in "Hf":
                at = _numbers(params) + [1]
                row, col = max(0, at[0] - 1), max(0, at[1] - 1)
            elif final == "K":
                erase_line(rows.get(row), col, _numbers(params, 0)[0])
            elif final == "J" and _numbers(params, 0)[0] == 2:
                rows.clear()
        elif token == "\r":
            col = 0
        elif token == "\n":
            row, col = row + 1, 0
        elif token == "\b":
            col = max(0, col - 1)
        elif token == "\t":
            col = (col // 8 + 1) * 8
        elif not token.startswith("\x1b"):
            cells = rows.setdefault(row, {})
            for char in token:
                cells[col] = char
                col += 1
                if unicodedata.east_asian_width(char) in "WF":
                    cells[col] = ""        # a wide character fills two cells
                    col += 1
    if not rows:
        return ""
    return "\n".join(line_of(rows.get(r)) for r in range(max(rows) + 1))


def erase_line(cells: dict | None, col: int, mode: int) -> None:
    if not cells:
        return
    for at in list(cells):
        if mode == 2 or (mode == 0 and at >= col) or (mode == 1 and at <= col):
            del cells[at]


def line_of(cells: dict | None) -> str:
    if not cells:
        return ""
    return "".join(cells.get(at, " ") for at in range(max(cells) + 1))


def logs(bg_id: str, config_dir=None) -> str:
    """`claude logs <id>` under `config_dir`, as the terminal would show it (`screen`)."""
    result = run(["logs", bg_id], env=scoped_env(config_dir), raw=True)
    # each stream is its own screen: stderr drawn on stdout's grid would start wherever the
    # redraw left the cursor
    return "\n".join(part for part in (screen(result.stdout), screen(result.stderr)) if part)


# WHAT `claude stop` SAYS WHEN IT ASKS TO BE TRIED AGAIN (r-17): it could not confirm the
# stop because its background service may be restarting. Only that answer is retried, once,
# after this pause; anything else is a real failure and raises the first time.
STOP_RESTARTING = "the background service may be restarting"
STOP_RETRY_PAUSE = 2.0
# WHEN THE RETRY STILL CANNOT CONFIRM IT (r-25), the listing is asked instead: a stopped
# session drops out of `claude agents --json` within seconds, not at once, so it is looked
# at up to this many times, this far apart, before a row that is still there is believed.
STOP_LOOKS = 5
STOP_LOOK_PAUSE = 2.0


def stop(bg_id: str, config_dir=None) -> None:
    """`claude stop <id>`: a human tap, or the session a resume has just superseded
    (`house.retire_superseded`); never a session that is doing something.

    Raises HarnessError with ONE line, because the voice door hands it to him as the reason
    a connect was refused (`housetier.open_here`). The harness's own words, except when
    it could not confirm the stop twice: then the listing decides (`_gone_after`), and a
    session still listed is said plainly, with the command he can run."""
    said = _stop_once(bg_id, config_dir)
    if said and STOP_RESTARTING in said:
        time.sleep(STOP_RETRY_PAUSE)
        said = _stop_once(bg_id, config_dir)
        if said and STOP_RESTARTING in said:
            return _gone_after(bg_id, config_dir)
    if said is not None:
        raise HarnessError(f"claude stop {bg_id} {said}")


def stop_command(bg_id: str, config_dir=None) -> str:
    """The command that stops this session from his own terminal: the space's config dir
    named in front, since the bare command under his default dir cannot see it."""
    prefix = f"CLAUDE_CONFIG_DIR={config_dir} " if config_dir is not None else ""
    return f"{prefix}claude stop {bg_id}"


def _gone_after(bg_id: str, config_dir) -> None:
    """Returns once the listing no longer shows `bg_id`; raises when it still does after
    `STOP_LOOKS` looks, or when the listing never answers (not knowing is not gone)."""
    listed, answered = True, False
    for look in range(STOP_LOOKS):
        if look:
            time.sleep(STOP_LOOK_PAUSE)
        try:
            rows = agents(config_dir, strict=True)
        except HarnessError:
            continue
        answered = True
        listed = find(bg_id, rows) is not None
        if not listed:
            return
    command = stop_command(bg_id, config_dir)
    if not answered:
        raise HarnessError(f"the house's session {bg_id} could not be confirmed stopped, and "
                           f"the session listing did not answer; run `{command}` and connect again")
    raise HarnessError(f"the house's session {bg_id} is still running and would not stop; "
                       f"run `{command}` and connect again")


def _stop_once(bg_id: str, config_dir) -> str | None:
    """None when the stop worked, else what it said, as `exited <code>: <words>`."""
    result = run(["stop", bg_id], env=scoped_env(config_dir))
    if result.returncode == 0:
        return None
    words = " ".join((result.stderr or result.stdout or "").split())
    return f"exited {result.returncode}: {words}" if words else f"exited {result.returncode}"


def _assistant_texts(record: dict) -> list[str]:
    if record.get("type") != "assistant" or record.get("isSidechain"):
        return []
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")]


def last_said(transcript_path: str | Path, n: int = 40) -> str:
    """The last `n` lines of assistant text in a transcript jsonl; "" when unreadable."""
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return ""
    lines: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            for text in _assistant_texts(record):
                lines.extend(text.splitlines())
    return "\n".join(lines[-n:])
