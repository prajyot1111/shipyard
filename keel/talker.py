"""`keel talker`: the talker's runtime.

The talker is one long-lived Claude Code conversation (Harbor) run by
`claude remote-control --name harbor` in server mode, under its own config dir
(`spaces/harbor/.claude`) from the `talker/` working directory. Verbs:

    install [--load]   write dev.keel.talker.plist (macOS) or dev.keel.talker.service into the
                       services directory (the install's services/, a bare checkout's etc/)
                       (Linux), seed the config dir's .claude.json from the old Harbor
                       config dir, link the auto-memory path to the memory (the install's memory/talker/, c-722)
                       and the config dir's CLAUDE.md to the rulebook beside it; `--load`
                       also starts the service (`keel/service.py`)
    start [--session-id ID]
                       run the server in the foreground (what the service runs): stamp the
                       run, assert consent in the config dir's .claude.json, then the claude
                       pid goes to state/talker.pid, its output to stdout (the log), and
                       the session id it prints to state/talker.session; a y/n prompt is a
                       fault (keel/talkerwatch.py), never answered.
                       A plain restart in the same directory reconnects the same
                       session (verified, <install>/history/docs/talker.md); `--session-id` reattaches one
                       explicitly
    fresh              rotate to a new run dir so Remote Control mints a clean 'Harbor':
                       bump the run-dir pointer, re-seed trust and re-link memory for the
                       new cwd, restart the service, confirm a new session id (durable memory
                       is unchanged, so the new conversation still knows everything durable)
    shell [--print]    open a NEW interactive Harbor thread in the run dir over plain SSH
                       (a fresh thread, not the phone conversation; see the probe in
                       <install>/history/docs/talker.md); `--print` prints the incantation instead of exec-ing
    turn start|over    the UserPromptSubmit and Stop hooks of its config dir: this run's
                       sessions and whether each has ended its turn (keel/talkerturn.py),
                       which is when the drain may rotate it for a memory change
    url                the newest claude.ai/code session URL from state/logs/talker.log,
                       falling back to the config dir's transcripts
    status             pid, health, recorded session, URL, current run dir, session age and
                       size, and what `claude agents --json` says; exits 1 on any fault
    stop               SIGTERM the recorded pid (never by pattern)

The run directory rotates: a session is pinned to its cwd on Remote Control's backend and
reconnected there on every start, so a fresh conversation means a new numbered run dir
(talker/home/1, /2, ...) recorded in the pointer file state/talker-cwd. `keel talker fresh`
does that by hand and the drain does it automatically when the current run is older
than a day (`upkeep` / `reset_due`), timed off the pointer file's mtime, a clock Keel owns,
or when Harbor's memory moved on main and the run is between turns (`keel/talkerturn.py`).

Everything the verbs know comes from the config (the install's `config.toml`) through `keel.config`: the state dir
gives the log, pid, session and pointer paths; the repo root gives the config dir and cwd.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from keel import childenv, claudejson, configpath, harness, logins, memoryroot, talkerturn, talkerwatch, config as config_module, service as service_module
from keel.models import TURN_MODELS
# The config dir and the run dirs, split out of this module when it passed 600 lines; the
# names are re-exported because every caller and test reaches them as `talker.<name>`.
from keel.talkerdirs import (KEEP_RUNS, SEED_KEYS, forget_run,  # noqa: F401
                             link_memory, link_rules, link_skills, project_slug, rules_note, prune_runs, rotate, run_dirs,
                             seed_claude_json, seed_trust)

LABEL = "dev.keel.talker"
# THE TMUX SOCKET THE LINUX UNIT RUNS `start` ON (<install>/history/docs/vps-plan.md, insurance item 6). It is
# a host and nothing more: systemd starts and restarts it, the pane's output is teed into
# the same log launchd writes, and Keel never reads, captures or types into the pane. What
# it adds on a box with nobody at a desk is a place to `tmux -L keel-talker attach` over
# SSH and watch the server live. Its own socket, so it is the only session on its server
# and the server exits when the talker does, which is what systemd restarts on.
TMUX_SOCKET = "keel-talker"
NAME = "Harbor"
CAPACITY = 1
URL_RE = re.compile(r"https://claude\.ai/code/(session_[A-Za-z0-9]+)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")  # CSI only; an OSC 8 link keeps its URL text
STOP_TIMEOUT = 15
POINTER = "talker-cwd"       # state file: the current run-dir index
HANDOFF = "talker-handoff"   # state file: a dated breadcrumb, one line per reset
FIRST_RUN = 1                # the first numbered run dir is talker/home/1
NEW_SESSION_TIMEOUT = 30     # how long `fresh` waits for the restarted agent to print a new id


@dataclass
class Paths:
    root: Path
    state_dir: Path
    # Whose service directory the loaded copy lives in; a test passes a tmpdir
    # (`keel/backup.py` records why a real home is never assumed).
    home: Path = field(default_factory=Path.home)
    # The model the server's sessions run on: `[models] converse`, the voice conversation's,
    # since Harbor on the phone is the same conversation by another door (J-4).
    model: str = TURN_MODELS["converse"]
    # `[machine] harbor_dir`: the old Harbor tree, whose `.claude/.claude.json` seeds the
    # talker's onboarding and account state. None: nothing is seeded but the trust entry.
    harbor_dir: Path | None = None
    # The toml the service is told to read (`config.named_toml`, c-711): the config `install`
    # was run with, when it is not the checkout's own. None: the checkout's own is right.
    config: str | None = None
    # The install this talker runs for (c-722): its memory lives there (`keel/memoryroot.py`).
    # None: a checkout with no install, whose `talker/memory` is the memory.
    install: Path | None = None
    # Where its service file is rendered (c-722, `Config.services_dir`): the install's
    # `services/`. None: the checkout's `etc/`.
    services: Path | None = None

    @property
    def seed_source(self) -> Path | None:
        return self.harbor_dir / ".claude" / ".claude.json" if self.harbor_dir else None

    @property
    def config_dir(self) -> Path:
        return self.root / "spaces" / "harbor" / ".claude"

    @property
    def run_base(self) -> Path:
        """The container of the numbered run dirs, and the launchd WorkingDirectory. Remote
        Control pins one session to a directory on its own backend and reconnects it on
        every start, so a fresh conversation must be a directory nothing else has opened a
        session in (a consent probe on 2026-09-17 pinned a session named harbor-probe3 to
        talker/ that no local file could dislodge). Each conversation therefore gets its own
        numbered subdirectory here (talker/home/1, /2, ...); the base itself is never a cwd,
        so nothing is ever pinned to it."""
        return self.root / "talker" / "home"

    @property
    def cwd_pointer(self) -> Path:
        """The state file that records which numbered run dir is current."""
        return self.state_dir / POINTER

    def run_index(self) -> int:
        """The current run-dir number from the pointer file; FIRST_RUN when it is unset."""
        text = read_text(self.cwd_pointer)
        return int(text) if text.isdigit() and int(text) >= FIRST_RUN else FIRST_RUN

    @property
    def cwd(self) -> Path:
        """Where the server runs: the current numbered run dir under run_base. Reading the
        pointer on every access means `start` (under launchd) always picks up a rotation."""
        return self.run_base / str(self.run_index())

    @property
    def handoff_file(self) -> Path:
        """The dated breadcrumb log, one line per reset (state/, not injected memory)."""
        return self.state_dir / HANDOFF

    @property
    def memory_src(self) -> Path:
        """The install's `memory/talker` once it holds one, else the checkout's `talker/memory`."""
        return memoryroot.dir_of(memoryroot.TALKER, self.install, self.root)

    @property
    def memory_link(self) -> Path:
        return self.config_dir / "projects" / project_slug(self.cwd) / "memory"

    @property
    def rules_src(self) -> Path | None:
        """The rulebook beside the talker's memory (c-722 landing B), else the shipped one, but
        only for a memory the shipped one was written for (r1.F10): one `shipyard init` seeded
        from the template, by its seeding record (`memoryroot.seeded`, r3.F4), or none yet.
        An owner's own memory (moved in before the rulebook was) gets None, whatever its
        files are called, and nothing is linked."""
        own = self.memory_src / memoryroot.RULEBOOK
        if own.is_file():
            return own
        template = self.root / memoryroot.TEMPLATE[memoryroot.TALKER]
        fits = not self.memory_src.is_dir() or memoryroot.seeded(memoryroot.TALKER, self.install)
        return template / memoryroot.RULEBOOK if fits else None

    @property
    def skills_dir(self) -> Path:
        return self.config_dir / "skills"

    @property
    def rules_link(self) -> Path:
        return self.config_dir / memoryroot.RULEBOOK

    @property
    def log(self) -> Path:
        return self.state_dir / "logs" / "talker.log"

    @property
    def pid_file(self) -> Path:
        return self.state_dir / "talker.pid"

    @property
    def session_file(self) -> Path:
        return self.state_dir / "talker.session"

    @property
    def etc(self) -> Path:
        return self.services or self.root / "etc"

    @property
    def manager(self) -> service_module.Manager:
        return service_module.Manager(self.home)


def paths_from(config) -> Paths:
    return Paths(root=config.root, state_dir=config.state_dir,
                 model=config.turn_models["converse"], harbor_dir=config.harbor_dir,
                 config=config_module.named_toml(config), install=config.install_home,
                 services=getattr(config, "services_dir", None))


# ----- install -----

def service(paths: Paths, home: Path | None = None) -> service_module.Service:
    """`keel talker start` from the run base, restarted whenever it exits, logs under
    state/. On Linux it runs inside tmux (`TMUX_SOCKET`)."""
    home = home or paths.home
    path = ":".join([str(home / ".local" / "bin"), "/opt/homebrew/bin", str(paths.root / "bin"),
                     "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    return service_module.Service(
        label=LABEL,
        description="Keel talker (Remote Control)",
        argv=[str(paths.root / "bin" / "keel"), "talker", "start"],
        # The service's cwd is the stable base; `start` sets the claude child's cwd to the
        # current numbered run dir itself (`spawn`), reading the pointer afresh each start.
        cwd=paths.run_base,
        env={
            "PATH": path,
            "HOME": str(home),
            "KEEL_HOME": str(paths.root),
            **({config_module.CONFIG_ENV: paths.config} if paths.config else {}),
            "CLAUDE_CONFIG_DIR": str(paths.config_dir),
        },
        stdout=paths.log,
        stderr=paths.log,
        throttle=10,
        tmux=TMUX_SOCKET,
    )


def render_plist(paths: Paths, home: Path | None = None) -> bytes:
    return service_module.plist(service(paths, home))


def install(paths: Paths, load: bool = False) -> int:
    paths.run_base.mkdir(parents=True, exist_ok=True)   # the service's cwd must exist to start
    written = paths.manager.write(service(paths), paths.etc)
    seed_claude_json(paths.seed_source, paths.config_dir / ".claude.json", paths.cwd)
    link_memory(paths)
    link_rules(paths)
    skills = link_skills(paths)
    for path in written:
        print(f"wrote {path}")
    print(configpath.reads_line(paths.config, paths.root))
    print(f"seeded {paths.config_dir / '.claude.json'}")
    print(f"linked {paths.memory_link} -> {paths.memory_src}")
    print(rules_note(paths))
    for name in skills:
        print(f"linked {paths.skills_dir / name}")
    if load:
        return paths.manager.load(service(paths), paths.etc)
    print("not loaded; `keel talker install --load` when ready")
    return 0


# ----- transcript size and age (auto-reset input) -----

def project_dir(config_dir: Path, cwd: Path) -> Path:
    return config_dir / "projects" / project_slug(cwd)


def reset_due(now: float, rotated_at: float | None, max_age_seconds: int) -> str | None:
    """The auto-reset predicate: a reason string when the current run is older than
    `max_age_seconds`, None otherwise. `rotated_at` is a clock KEEL owns: the mtime of the
    run-dir pointer, written when the run began (a rotation, or the first start). It is NOT
    the transcript's mtime: a Remote Control session keeps its turns in a remote environment,
    so the local transcript is 0 bytes and its mtime is the last RECONNECT, which any restart
    inside the window would rewind (a subagent review on 2026-09-17 caught this). Neither
    the context size nor the true idle of the conversation is visible locally, so age since
    the run began is the honest signal, the way Harbor reset every morning; a reset at a day
    old is rare and recoverable (keep talking, or run `keel talker fresh`). No pointer yet
    (never started) is never reset."""
    if rotated_at is None:
        return None
    age = now - rotated_at
    if age < max_age_seconds:
        return None
    return f"run ~{int(age)}s old"


def write_breadcrumb(paths: Paths, session: str, tokens: int, reason: str | None) -> None:
    """Append a dated one-line note that a reset happened, so the run-dir history is
    traceable even though durable memory already carries the substance. Kept in state/, not
    in the injected memory, so it never grows a live turn's context."""
    when = datetime.now().astimezone().isoformat(timespec="seconds")
    note = f"{when} reset run {paths.run_index()} session {session or 'none'} ~{tokens} tokens"
    if reason:
        note += f" ({reason})"
    paths.handoff_file.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.handoff_file, "a", encoding="utf-8") as handle:
        handle.write(note + "\n")


# ----- fresh: rotate the run dir and restart the agent -----

def restart_agent(paths: Paths) -> dict:
    """Restart the talker's service so it comes up in the new cwd. `launchctl kickstart
    -k` or `systemctl --user restart` stops the running instance and starts it again in
    one step, which reads the pointer afresh; a plain stop would only bounce it back into
    the SAME cwd under KeepAlive. Falls back to a SIGTERM of the recorded pid when the
    service is not loaded (a standalone dev run)."""
    ok, how = paths.manager.restart(LABEL)
    if ok:
        return {"ok": True, "how": how}
    pid = recorded_pid(paths)
    if alive(pid):
        os.kill(pid, signal.SIGTERM)
        return {"ok": True, "how": "sigterm (KeepAlive restarts it in the new cwd)"}
    return {"ok": False, "how": how}


def await_new_session(paths: Paths, previous: str, timeout: int = NEW_SESSION_TIMEOUT) -> str | None:
    """Poll state/talker.session for a session id that differs from `previous`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = read_text(paths.session_file)
        if current and current != previous:
            return current
        time.sleep(0.5)
    return None


def do_fresh(paths: Paths, reason: str | None = None) -> dict:
    """Rotate to a fresh run dir and restart the agent so Remote Control mints a new
    'Harbor'. Durable memory is untouched and re-linked, so the new conversation still
    knows everything durable. Returns a summary dict; prints nothing (the caller reports)."""
    old_index = paths.run_index()
    old_session = read_text(paths.session_file)
    pointer = paths.cwd_pointer
    old_age = int(time.time() - pointer.stat().st_mtime) if pointer.is_file() else 0
    write_breadcrumb(paths, old_session, old_age, reason)
    new_index = rotate(paths)
    talkerturn.record_run(paths, new_index)      # the memory the new run starts on (c-538)
    paths.session_file.unlink(missing_ok=True)   # so the NEW id is detectable
    restart = restart_agent(paths)
    new_session = await_new_session(paths, old_session) if restart["ok"] else None
    return {"old_index": old_index, "new_index": new_index, "old_session": old_session,
            "old_age": old_age, "new_session": new_session, "cwd": str(paths.cwd),
            "restart": restart, "reason": reason}


def fresh(paths: Paths) -> int:
    """`keel talker fresh`: rotate the run dir so the next conversation is a clean 'Harbor'."""
    result = do_fresh(paths)
    print(f"talker: rotated run dir {result['old_index']} -> {result['new_index']} "
          f"(previous run was ~{result['old_age']}s old, durable memory carried over), "
          f"now {result['cwd']}")
    if not result["restart"]["ok"]:
        print(f"talker: could not restart the agent: {result['restart']['how']}", file=sys.stderr)
        return 1
    if result["new_session"]:
        print(f"talker: new session {result['new_session']} ({NAME})")
        return 0
    print("talker: restarted; a new session id has not appeared yet, check `keel talker status`",
          file=sys.stderr)
    return 0


def upkeep(cfg, now: float | None = None, holding: bool = True) -> dict:
    """Called by the drain every pass. Rotate the talker to a fresh conversation when the
    current run is older than the max age (`reset_due`, off Keel's own pointer clock), or
    when Harbor's memory moved on main since the run began and its hooks say it is between
    turns with no voice hold live (`holding`, which defaults to waiting, `keel/talkerturn.py`,
    c-538); never when the
    talker is not running. Runs regardless of `drain_paused`: it maintains the talker, not
    houses, so pausing the drain (which only stops new houses) does not stop talker upkeep."""
    paths = paths_from(cfg)
    if not alive(recorded_pid(paths)):
        return {"reset": False, "reason": "talker not running"}
    pointer = paths.cwd_pointer
    rotated_at = pointer.stat().st_mtime if pointer.is_file() else None
    reason = (reset_due(now if now is not None else time.time(), rotated_at,
                        cfg.talker_reset_max_age_seconds)
              or talkerturn.due(paths, holding))
    if reason is None:
        return {"reset": False, "reason": "not due"}
    result = do_fresh(paths, reason=f"auto-reset ({reason})")
    return {"reset": True, "reason": reason, "result": result}


# ----- shell: a terminal Harbor over SSH -----

def shell_incantation(paths: Paths) -> str:
    """The command that opens a terminal Harbor: the run dir, its config dir, plain claude."""
    return f"cd {paths.cwd} && CLAUDE_CONFIG_DIR={paths.config_dir} claude"


def shell(paths: Paths, print_only: bool = False) -> int:
    """`keel talker shell`: open a NEW interactive Harbor thread in the run dir under the
    talker's config, memory and rules. A fresh thread, not the phone conversation: a probe
    on 2026-09-17 (<install>/history/docs/talker.md) found a terminal cannot join the live Remote Control
    session (`remote-control -c` refuses a session another instance already serves, and the
    server keeps its turns in the remote environment, so the local transcript is empty and
    `--resume` finds no conversation). Same board through `kb`, same memory, separate
    history. Works over plain SSH with no browser. `--print` (or no tty) prints the
    incantation instead of exec-ing, so it is safe to test and to eval from a wrapper."""
    paths.cwd.mkdir(parents=True, exist_ok=True)
    seed_trust(paths)
    link_memory(paths)
    if print_only or not sys.stdout.isatty():
        print(shell_incantation(paths))
        return 0
    os.chdir(paths.cwd)
    os.execvpe("claude", ["claude"], environment(paths))
    return 1   # unreachable when exec succeeds


# ----- start -----

def command(session_id: str | None = None) -> list[str]:
    """The server command. Plain, it reconnects the directory's preserved environment
    and its session; `--session-id` reattaches one session explicitly."""
    argv = ["claude", "remote-control", "--name", NAME]
    if session_id:
        argv += ["--session-id", session_id]
    else:
        argv += ["--capacity", str(CAPACITY)]
    return argv


def environment(paths: Paths) -> dict:
    """The talker's config dir, and its model pinned in `ANTHROPIC_MODEL` (J-4): every
    session the server starts reads it, where `--model` is a global flag `remote-control`
    may not take. It beats the config dir's settings and an inherited value."""
    env = childenv.own_env()      # Harbor is not him: never his token (c-451)
    harness.point_env(env, paths.config_dir)
    env["KEEL_HOME"] = str(paths.root)
    env["ANTHROPIC_MODEL"] = paths.model
    return env


def read_text(path: Path) -> str:
    return path.read_text().strip() if path.exists() else ""


def session_in(text: str) -> str | None:
    """The last `session_...` id in a log, with terminal escapes stripped first."""
    found = URL_RE.findall(ANSI_RE.sub("", text))
    return found[-1] if found else None


def spawn(paths: Paths, session_id: str | None) -> subprocess.Popen:
    paths.cwd.mkdir(parents=True, exist_ok=True)
    # ITS TURN HOOKS COUNT ONLY THE SERVER'S SESSIONS (c-538): not a voice turn, not a
    # `keel talker shell` thread, whose stopped turn would hold the memory rotation (r1.F3).
    env = dict(environment(paths), **{talkerturn.ENV: "1"})
    return subprocess.Popen(command(session_id), cwd=paths.cwd, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)


def forward_signals(child: subprocess.Popen) -> None:
    def relay(signum, frame):
        if child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, relay)
    signal.signal(signal.SIGINT, relay)
    signal.signal(signal.SIGHUP, relay)     # tmux hangs the pane up when its unit stops


def relay_output(child: subprocess.Popen, paths: Paths) -> None:
    """Echo the server's output to stdout AS IT ARRIVES, in chunks rather than lines (a
    prompt has no newline), record the session id the first time this run sees it (so the
    session file's mtime says this run, even when the id is the same as last run's), and
    fault on a y/n prompt seen before any session URL (`keel/talkerwatch.py`). Words that
    say its login is gone mark the talker dir's Logins row, once a run (c-558)."""
    relay = talkerwatch.Relay(URL_RE)
    fd = child.stdout.fileno()
    marked = False
    while chunk := os.read(fd, 4096):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        if not marked:
            marked = logins.saw_at(paths.state_dir, paths.config_dir,
                                   chunk.decode(errors="replace"))
        found = relay.feed(chunk)
        if "session" in found:
            paths.session_file.write_text(found["session"] + "\n")
            if talkerwatch.read_fault(paths.state_dir):
                talkerwatch.fault_path(paths.state_dir).unlink(missing_ok=True)
        if "prompt" in found and not talkerwatch.read_fault(paths.state_dir):
            fault(paths, f"unanswered prompt, nothing will answer it: {found['prompt']}")


def fault(paths: Paths, text: str) -> None:
    """Record why this run cannot serve, and say so in the log."""
    talkerwatch.write_fault(paths.state_dir, text)
    print(f"\ntalker: FAULT {text}", flush=True)


def assert_consent(paths: Paths) -> bool:
    """`remoteDialogSeen: true` in the config dir's .claude.json before the server reads
    it; False (with a fault) when the file does not parse, which is never written over."""
    try:
        if claudejson.ensure_consent(paths.config_dir / claudejson.NAME):
            print(f"talker: recorded remoteDialogSeen in {paths.config_dir / claudejson.NAME}",
                  flush=True)
        return True
    except claudejson.Unreadable as error:
        fault(paths, f"cannot assert Remote Control consent, the config does not parse: {error}")
        return False


def start(paths: Paths, session_id: str | None = None) -> int:
    """Run the server in the foreground, recording its pid and its session."""
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    if not paths.cwd_pointer.is_file():
        paths.cwd_pointer.write_text(f"{paths.run_index()}\n")   # birth time for the age clock
    talkerwatch.mark_start(paths.state_dir)
    # Every start relinks the rulebook and the skills (r1.F1): a deploy that took the tracked
    # rulebook out of the config dir leaves the service to put the link back, unasked.
    link_rules(paths)
    print(f"talker: {rules_note(paths)}", flush=True)
    for name in link_skills(paths):
        print(f"talker: linked {paths.skills_dir / name}", flush=True)
    if not assert_consent(paths):
        return 2
    child = spawn(paths, session_id)
    paths.pid_file.write_text(f"{child.pid}\n")
    forward_signals(child)
    print(f"talker: pid {child.pid}, cwd {paths.cwd}, config {paths.config_dir}", flush=True)
    relay_output(child, paths)
    code = child.wait()
    print(f"talker: claude exited {code}", flush=True)
    return code


# ----- url, status, stop -----

def newest_url(text: str) -> str | None:
    """The last claude.ai/code session URL in a log or transcript, without the
    `?from=cli` suffix the server prints."""
    session_id = session_in(text)
    return f"https://claude.ai/code/{session_id}" if session_id else None


def transcript_url(config_dir: Path) -> str | None:
    """Newest transcript first, as `harbor url` did: /clear starts a fresh transcript
    that never carries the URL, so the newest file alone is not enough."""
    files = sorted(config_dir.glob("projects/*/*.jsonl"), key=lambda f: f.stat().st_mtime,
                   reverse=True)
    for path in files:
        url = newest_url(path.read_text(errors="replace"))
        if url:
            return url
    return None


def url_for(paths: Paths) -> str | None:
    return newest_url(read_text(paths.log)) or transcript_url(paths.config_dir)


def url(paths: Paths) -> int:
    found = url_for(paths)
    if not found:
        print("no Remote Control URL yet; is the talker running?", file=sys.stderr)
        return 1
    print(found)
    return 0


def agents() -> list[dict]:
    """`claude agents --json`, or an empty list when the harness cannot answer."""
    try:
        done = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True,
                              timeout=20)
        return json.loads(done.stdout) if done.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def talker_agent(rows: list[dict]) -> dict | None:
    """The agents row named `harbor`, if the harness lists one (server-mode sessions
    were not listed in the phase 5 probe; a row appears only for a running turn)."""
    ours = [row for row in rows if row.get("name") == NAME]
    ours.sort(key=lambda row: row.get("startedAt") or 0)
    return ours[-1] if ours else None


def recorded_pid(paths: Paths) -> int | None:
    text = read_text(paths.pid_file)
    return int(text) if text.isdigit() else None


def process_command(pid: int) -> str:
    done = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return done.stdout.strip()


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return "claude" in process_command(pid)



def installed(paths: Paths) -> bool:
    """This machine's service manager has the talker's unit or plist."""
    manager = paths.manager
    suffix = ".service" if manager.kind == service_module.SYSTEMD else ".plist"
    return (manager.installed_dir / f"{LABEL}{suffix}").exists()


def health(paths: Paths, now: float | None = None) -> dict:
    """The talker's verdict (`talkerwatch.verdict`): stopped, faulted, still starting, no
    session after a minute, or serving the session THIS run recorded."""
    session_file = paths.session_file
    return talkerwatch.verdict(
        installed=installed(paths), running=alive(recorded_pid(paths)),
        now=time.time() if now is None else now,
        started=talkerwatch.started_at(paths.state_dir),
        session_at=session_file.stat().st_mtime if session_file.is_file() else None,
        session=read_text(session_file), fault=talkerwatch.read_fault(paths.state_dir))


def status(paths: Paths) -> int:
    """Exits 1 on any fault in `health`, not only when the process is gone: a server alive
    with no session is not serving anyone (c-444)."""
    pid = recorded_pid(paths)
    running = alive(pid)
    verdict = health(paths)
    row = talker_agent(agents())
    print(f"talker: {'running' if running else 'not running'}"
          + (f" (pid {pid})" if pid else " (no pid file)"))
    print(f"health: {verdict['state']}, {verdict['reason']}")
    print(f"session: {read_text(paths.session_file) or 'none recorded'}")
    print(f"harness: {row['sessionId'] + ' ' + str(row.get('status')) if row else 'no harbor row in claude agents'}")
    found = url_for(paths)
    current = verdict["state"] in ("serving",)
    print(f"url: {found if current else 'none this run' + (f' (last seen {found})' if found else '')}")
    print(f"cwd: {paths.cwd} (run {paths.run_index()})")
    pointer = paths.cwd_pointer
    if pointer.is_file():
        print(f"run age: rotated ~{int(time.time() - pointer.stat().st_mtime)}s ago "
              f"(turns live in Remote Control, not a local transcript)")
    else:
        print("run age: not recorded yet")
    print(talkerturn.state(paths))
    print(f"config: {paths.config_dir}")
    return 0 if running and verdict["ok"] else 1


def stop(paths: Paths) -> int:
    """SIGTERM the recorded pid, SIGKILL after STOP_TIMEOUT; never a pattern."""
    pid = recorded_pid(paths)
    if not alive(pid):
        print("talker: not running", file=sys.stderr)
        paths.pid_file.unlink(missing_ok=True)
        return 1
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + STOP_TIMEOUT
    while alive(pid) and time.time() < deadline:
        time.sleep(0.5)
    if alive(pid):
        os.kill(pid, signal.SIGKILL)
    paths.pid_file.unlink(missing_ok=True)
    print(f"talker: stopped pid {pid}")
    return 0


def turn(paths: Paths, event: str) -> int:
    """`keel talker turn start|over`: the talker's UserPromptSubmit and Stop hooks. Always 0:
    a hook that fails must not hold his turn."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        talkerturn.hook(paths, event, payload if isinstance(payload, dict) else {})
    except (OSError, ValueError):
        pass
    return 0


# ----- parser -----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel talker", description="the talker's runtime")
    subs = parser.add_subparsers(dest="verb", required=True)
    sub = subs.add_parser("install")
    sub.add_argument("--load", action="store_true", help="also start it under launchd (macOS) or systemd (Linux)")
    sub = subs.add_parser("start")
    sub.add_argument("--session-id", help="reattach this session instead of the directory's own")
    subs.add_parser("fresh")
    sub = subs.add_parser("shell")
    sub.add_argument("--print", dest="print_only", action="store_true",
                     help="print the incantation instead of exec-ing claude")
    sub = subs.add_parser("turn", help="a turn hook of Harbor's config dir: the hook JSON on stdin")
    sub.add_argument("event", choices=talkerturn.EVENTS)
    subs.add_parser("url")
    subs.add_parser("status")
    subs.add_parser("stop")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = paths_from(config_module.load())
    if args.verb == "install":
        return install(paths, load=args.load)
    if args.verb == "start":
        return start(paths, session_id=args.session_id)
    if args.verb == "fresh":
        return fresh(paths)
    if args.verb == "shell":
        return shell(paths, print_only=args.print_only)
    if args.verb == "turn":
        return turn(paths, args.event)
    return {"url": url, "status": status, "stop": stop}[args.verb](paths)
