"""One Keel process on this machine, as launchd or systemd runs it.

Every `keel * install` (the engine, the talker, the voice gateway, the backup's two jobs)
describes its process once, as a `Service`, and this module does the rest on either
platform: it renders a launchd plist on macOS or a systemd user unit on Linux (plus a
`.timer` for a scheduled job), writes it into the directory it is handed (`Config.services_dir`:
the install's `services/`, a bare checkout's `etc/`), and on `--load`
copies it where the service manager looks and starts it. `state`, `restart` and `unload`
are the same verbs read back.

The manager is chosen by `platform()`: launchd on macOS, systemd on Linux, and on anything
else (Windows) `UNSUPPORTED`, whose every verb raises `Unsupported` with one plain message
rather than writing a file nobody reads; `shipyard init` (`keel/installer.py`) and
`shipyard service` (`keel/appservices.py`) go through this one interface. Every path is relative to a `home` the caller
passes: a test that resolved against the process's real home once DELETED the live backup
agents (the note at `keel/backup.py`'s `LAUNCH_AGENTS`), so nothing here may reach one.

Linux-only knobs on a `Service` (`tmux`, `kill_mode`, `cpu_weight`, `credentials`) have no launchd
counterpart and are ignored there; the reasons they exist are on the callers that set them.
"""

import os
import plistlib
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

LAUNCHD = "launchd"
SYSTEMD = "systemd"
LAUNCH_AGENTS = Path("Library/LaunchAgents")
SYSTEMD_USER = Path(".config/systemd/user")
LINGER_DIR = Path("/var/lib/systemd/linger")
PROC_VERSION = Path("/proc/version")
SYSTEMD_BOOTED = Path("/run/systemd/system")     # what sd_booted(3) looks for: systemd is PID 1
PID_RE = re.compile(r'"PID"\s*=\s*(\d+)')
# `launchctl bootout` returns before launchd has let go of the label, and bootstrapping
# while it still holds it fails with "Bootstrap failed: 5: Input/output error", leaving the
# agent UNLOADED behind a message that reads like an ordinary complaint. Seen for real on
# 2026-09-17 (voice) and twice on 2026-09-18. So the unload is waited out: `launchctl list
# <label>` going non-zero is launchd saying it has really finished.
BOOTOUT_TRIES = 25
BOOTOUT_WAIT = 0.2
# A bootstrap is not a start (c-747): launchd loaded `dev.shipyard.fetch` on 2026-10-11 and
# never ran it ("state = not running", "runs = 0", "pended nondemand spawn = speculative")
# though its plist has RunAtLoad and KeepAlive, and `launchctl kickstart` started it at
# once. So a load ends with a kickstart, and whoever says "started" first waits this long
# for the manager to report a process (`Manager.running`): 25 looks, 5 seconds.
START_TRIES = 25
START_WAIT = 0.2
RESTART_SECONDS = 10        # launchd's ThrottleInterval default, and systemd's RestartSec here
SAFE_ARG = re.compile(r"^[A-Za-z0-9_@+=:,./-]+$")
LAUNCHD_DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")   # Weekday 0 and 7 are Sunday


UNSUPPORTED = "unsupported"
REFUSAL = ("services on {os} are not built: Shipyard runs on macOS (launchd) and Linux "
           "(systemd --user), and on Windows inside WSL2, which is Linux")


class Unsupported(OSError):
    """This operating system has no service manager behind the interface yet."""


def platform() -> str:
    if sys.platform.startswith("linux"):
        return SYSTEMD
    if sys.platform == "darwin":
        return LAUNCHD
    return UNSUPPORTED


def wsl_version(version: str | None = None, env: dict | None = None) -> int | None:
    """Which WSL this Linux is, 1 or 2, else None. WSL1 always reports its own fixed kernel,
    `4.4.0-<build>-Microsoft` with a capital M; any other kernel naming Microsoft is WSL2
    (`...-microsoft-standard-WSL2`, or a custom one), so a custom WSL2 kernel is never read as
    WSL1 and blocked. WSL sets `WSL_DISTRO_NAME`; with it and no Microsoft kernel, it is WSL2
    on a custom kernel, which WSL1 cannot run. Keel runs on WSL2 as on any Linux, once systemd
    is on; WSL1 has none."""
    if version is None:
        try:
            version = PROC_VERSION.read_text(errors="replace")
        except OSError:
            version = ""
    if "-Microsoft" in version and "microsoft-standard" not in version.lower():
        return 1
    if "microsoft" in version.lower():
        return 2
    return 2 if (os.environ if env is None else env).get("WSL_DISTRO_NAME") else None


def on_wsl(version: str | None = None, env: dict | None = None) -> bool:
    """Whether this Linux is Windows' WSL, either version (`wsl_version`)."""
    return wsl_version(version, env) is not None


def systemd_booted(marker: Path = SYSTEMD_BOOTED) -> bool:
    """Whether systemd runs this machine (PID 1), so `systemctl --user` has a manager to
    ask. WSL leaves it off until /etc/wsl.conf turns it on."""
    return marker.is_dir()


@dataclass
class Service:
    label: str
    description: str
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    stdout: Path
    stderr: Path
    keep_alive: bool = True              # restarted whenever it exits; False is a job
    run_at_load: bool = True
    throttle: int | None = None          # seconds between restarts
    interval: int | None = None          # a job every this many seconds
    calendar: dict | None = None         # a job on launchd's {"Weekday", "Hour", "Minute"}
    tmux: str | None = None              # systemd: run argv inside a detached tmux on this socket
    kill_mode: str | None = None         # systemd: `process` keeps the children on a stop
    cpu_weight: int | None = None        # systemd: its share against the other units
    credentials: dict[str, Path] = field(default_factory=dict)   # systemd: LoadCredential name -> source

    @property
    def scheduled(self) -> bool:
        return self.interval is not None or self.calendar is not None


# ----- launchd -----

def plist(service: Service) -> bytes:
    doc = {
        "Label": service.label,
        "ProgramArguments": [str(arg) for arg in service.argv],
        "WorkingDirectory": str(service.cwd),
        "EnvironmentVariables": dict(service.env),
        "StandardOutPath": str(service.stdout),
        "StandardErrorPath": str(service.stderr),
    }
    if service.keep_alive:
        doc["KeepAlive"] = True
    doc["RunAtLoad"] = service.run_at_load
    if service.throttle is not None:
        doc["ThrottleInterval"] = service.throttle
    if service.interval is not None:
        doc["StartInterval"] = service.interval
    if service.calendar is not None:
        doc["StartCalendarInterval"] = dict(service.calendar)
    return plistlib.dumps(doc, sort_keys=False)


# ----- systemd -----

def quote(arg: str) -> str:
    """One ExecStart argument. `%` is a unit specifier and `$` an environment reference in
    ExecStart, so both are doubled whether or not the argument needs quotes."""
    text = str(arg).replace("%", "%%").replace("$", "$$")
    if SAFE_ARG.match(text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def env_line(key: str, value: str) -> str:
    text = f"{key}={value}".replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return f'Environment="{text}"'


def tmux_argv(service: Service) -> list[str]:
    """The tmux server hosts `argv` in a detached session on its own socket, so it is the
    only session there and the server exits with it, which is what systemd restarts on.
    The pane's output is teed into the log: that file stays the reading, never the pane."""
    command = f"{shlex.join(str(a) for a in service.argv)} 2>&1 | tee -a {shlex.quote(str(service.stdout))}"
    return ["/usr/bin/tmux", "-L", service.tmux, "new-session", "-d", "-s", service.tmux, command]


def unit(service: Service) -> str:
    lines = ["[Unit]", f"Description={service.description}"]
    if service.keep_alive:
        lines.append("StartLimitIntervalSec=0")          # launchd never gives up either
    lines += ["", "[Service]"]
    if service.scheduled:
        lines.append("Type=oneshot")
    elif service.tmux:
        lines.append("Type=forking")
    else:
        lines.append("Type=simple")
    argv = tmux_argv(service) if service.tmux else service.argv
    lines.append("ExecStart=" + " ".join(quote(arg) for arg in argv))
    if service.tmux:
        lines.append(f"ExecStop=/usr/bin/tmux -L {quote(service.tmux)} kill-server")
    lines.append(f"WorkingDirectory={quote(str(service.cwd))}")
    lines += [env_line(key, value) for key, value in service.env.items()]
    if not service.tmux:
        lines += [f"StandardOutput=append:{service.stdout}", f"StandardError=append:{service.stderr}"]
    if service.keep_alive:
        lines += ["Restart=always", f"RestartSec={service.throttle or RESTART_SECONDS}"]
    if service.kill_mode:
        lines.append(f"KillMode={service.kill_mode}")
    if service.cpu_weight is not None:
        lines.append(f"CPUWeight={service.cpu_weight}")
    # A MISSING SOURCE FAILS THE UNIT (status 243/CREDENTIALS, seen on systemd 255), so
    # whoever names a credential here also makes sure its source file exists.
    lines += [f"LoadCredential={name}:{str(source).replace('%', '%%')}"
              for name, source in service.credentials.items()]
    if not service.scheduled:
        lines += ["", "[Install]", "WantedBy=default.target"]
    return "\n".join(lines) + "\n"


def on_calendar(calendar: dict) -> str:
    day = calendar.get("Weekday")
    when = f"*-*-* {calendar.get('Hour', 0):02d}:{calendar.get('Minute', 0):02d}:00"
    return f"{LAUNCHD_DAYS[day]} {when}" if day is not None else when


def timer(service: Service) -> str:
    """The schedule, as launchd reads it. An interval job that runs at load fires as soon
    as the timer starts and then every interval after its last run; a calendar job that
    was missed (the machine was off) runs once when it is next up, as launchd does."""
    lines = ["[Unit]", f"Description={service.description} (schedule)", "", "[Timer]"]
    if service.interval is not None:
        if service.run_at_load:
            lines.append("OnActiveSec=0")
        lines.append(f"OnUnitActiveSec={service.interval}s")
    if service.calendar is not None:
        lines += [f"OnCalendar={on_calendar(service.calendar)}", "Persistent=true"]
    lines += ["", "[Install]", "WantedBy=timers.target"]
    return "\n".join(lines) + "\n"


# ----- the manager -----

@dataclass
class Manager:
    home: Path
    kind: str = field(default_factory=lambda: platform())   # late-bound, so a test can pin it

    def refuse(self) -> None:
        if self.kind not in (LAUNCHD, SYSTEMD):
            raise Unsupported(REFUSAL.format(os=sys.platform))

    @property
    def installed_dir(self) -> Path:
        self.refuse()
        return self.home / (LAUNCH_AGENTS if self.kind == LAUNCHD else SYSTEMD_USER)

    def files(self, service: Service) -> dict[str, bytes]:
        """File name to content, in the order they are loaded (the unit before its timer)."""
        self.refuse()
        if self.kind == LAUNCHD:
            return {f"{service.label}.plist": plist(service)}
        found = {f"{service.label}.service": unit(service).encode()}
        if service.scheduled:
            found[f"{service.label}.timer"] = timer(service).encode()
        return found

    def primary(self, service: Service) -> str:
        """The unit that is enabled and started: the timer for a job, else the service."""
        if self.kind == LAUNCHD:
            return service.label
        return f"{service.label}.{'timer' if service.scheduled else 'service'}"

    def write(self, service: Service, etc: Path) -> list[Path]:
        """Render into `etc` (the services directory it is handed) and make the log
        directories. Nothing on the
        machine changes."""
        for log in {service.stdout.parent, service.stderr.parent}:
            log.mkdir(parents=True, exist_ok=True)
        etc.mkdir(parents=True, exist_ok=True)
        written = []
        for name, content in self.files(service).items():
            (etc / name).write_bytes(content)
            written.append(etc / name)
        return written

    def load(self, service: Service, etc: Path) -> int:
        """Copy the written files where the manager looks, so a login or a boot brings them
        back, and (re)start the service now. A reinstall over a running one replaces it.

        On launchd the bootstrap is followed by a kickstart, the real start (c-747, the
        note at `START_TRIES`), for every service but a scheduled job, which runs on its
        schedule and not at every install. A zero says the manager took the commands, not
        that a process exists: `running` is how a caller sees one."""
        self.installed_dir.mkdir(parents=True, exist_ok=True)
        for name in self.files(service):
            shutil.copyfile(etc / name, self.installed_dir / name)
        if self.kind == LAUNCHD:
            code = self.bootstrap(service.label)
            if code != 0 or service.scheduled:
                return code
            code, complaint = self.kick(service.label)
            if code != 0:
                print(complaint)
            return code
        return self.enable(service)

    def kickstart(self, label: str) -> subprocess.CompletedProcess:
        """`launchctl kickstart` with no `-k`: it starts a loaded service that has no
        process and leaves one that is running as it is."""
        return subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{label}"],
                              capture_output=True, text=True)

    def kick(self, label: str) -> tuple[int, str]:
        """(code, what to say) of a kickstart, where the PID decides and not the exit code
        (r1.F1): a kickstart that complains about a label which has a process is a zero,
        since the service runs and a non-zero load is what has a caller take it back out
        (`appservices.forget` boots it out). Measured on 2026-10-11 (macOS, launchd):
        `launchctl kickstart gui/501/dev.shipyard.fetch` on a label running as pid 11114
        printed nothing and exited 0, pid and `runs = 1` unchanged, so the complaint is not
        the expected case; this is for the one nobody has seen."""
        done = self.kickstart(label)
        ok, text = said(done)
        if not ok and self.state(label)[1]:
            return 0, text
        return done.returncode, text

    def running(self, label: str, sleep=None) -> int | None:
        """The pid of a service that was just loaded or started, waited for: up to
        `START_TRIES` looks at `state`, `START_WAIT` apart, and None when no process showed.
        The pause is `sleep` (`time.sleep` unless one is handed in), so a test waits for
        nothing."""
        sleep = sleep or time.sleep
        for look in range(START_TRIES):
            pid = self.state(label)[1]
            if pid or look == START_TRIES - 1:
                return pid
            sleep(START_WAIT)
        return None

    def bootstrap(self, label: str) -> int:
        target = self.installed_dir / f"{label}.plist"
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        for _ in range(BOOTOUT_TRIES):
            if not self.state(label)[0]:
                break
            time.sleep(BOOTOUT_WAIT)
        done = subprocess.run(["launchctl", "bootstrap", domain, str(target)],
                              capture_output=True, text=True)
        print(done.stdout.strip() or done.stderr.strip() or f"loaded {label} from {target}")
        return done.returncode

    def enable(self, service: Service) -> int:
        """daemon-reload, enable, restart. Lingering is checked either way: without it, over
        SSH with no login session, there is no user manager at all and the first step fails
        with "Failed to connect to bus", which does not say why."""
        primary = self.primary(service)
        user = pwd.getpwuid(os.getuid()).pw_name
        code = 0
        for step in (["daemon-reload"], ["enable", primary], ["restart", primary]):
            done = systemctl(*step)
            if done.returncode != 0:
                said = done.stderr.strip() or f"systemctl --user {' '.join(step)} failed"
                if "connect to bus" in said:
                    said += (f" (no systemd user manager for {user}: log in to this machine "
                             f"as {user}, or run `sudo loginctl enable-linger {user}` once, "
                             f"then run this again)")
                print(said)
                code = done.returncode
                break
        else:
            print(f"enabled and started {primary} from {self.installed_dir}")
        if not lingering(user):
            print(LINGER_WARNING.format(user=user))
        return code

    def unload(self, service: Service, keep: bool = False) -> list[Path]:
        """Stop it, and remove the copies the manager reads. The services directory's copies
        are kept.

        `keep` leaves the installed copies where they are and does everything else: the job
        ends INSTALLED AND NOT LOADED on either manager (a bootout on launchd; on systemd
        the unit disabled and stopped, and a scheduled job's service stopped too). `stop`
        is not that: on systemd it stops the unit and leaves it enabled, which `state` reads
        as loaded. It is how a failed backup turn-on puts back a job whose file was there
        before it (`backupsetup.undo`). Returns the copies removed: none with `keep`."""
        if self.kind == LAUNCHD:
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{service.label}"],
                           capture_output=True)
        else:
            systemctl("disable", "--now", self.primary(service))
            if service.scheduled:
                systemctl("stop", f"{service.label}.service")
        removed = []
        for name in ([] if keep else self.files(service)):
            target = self.installed_dir / name
            target.unlink(missing_ok=True)
            removed.append(target)
        if self.kind == SYSTEMD and not keep:
            systemctl("daemon-reload")
        return removed

    def state(self, label: str, scheduled: bool = False) -> tuple[bool, int | None]:
        """(loaded, pid). Loaded is bootstrapped on launchd and enabled on systemd; a job
        is normally loaded with no pid, which is not the same as not installed."""
        self.refuse()
        if self.kind == LAUNCHD:
            done = subprocess.run(["launchctl", "list", label], capture_output=True, text=True)
            if done.returncode != 0:
                return False, None
            match = PID_RE.search(done.stdout)
            return True, int(match.group(1)) if match else None
        enabled = unit_property(f"{label}.{'timer' if scheduled else 'service'}", "UnitFileState")
        pid = unit_property(f"{label}.service", "MainPID")
        return enabled == "enabled", int(pid) if pid.isdigit() and int(pid) > 0 else None

    def resting(self, service: Service) -> bool:
        """A keep-alive service that was STOPPED and stays so, though it still reads as
        loaded: systemd only, where a stop leaves the unit enabled (`state`). The unit's
        `ActiveState` is `inactive` then. A unit that crashes is not: `Restart=always` with
        no start limit (`unit`) holds it `activating` between runs, never at rest, so
        `inactive` is somebody's stop, whether `shipyard service stop` or `systemctl --user
        stop` (r1.F4). This follows from systemd's documented states; no Linux machine was
        at hand to measure it on. launchd has no such state: a stop there is a bootout,
        which is not loaded. A job (not keep-alive) rests between its runs, so it is never
        said to be."""
        self.refuse()
        if self.kind != SYSTEMD or not service.keep_alive:
            return False
        return unit_property(f"{service.label}.service", "ActiveState") == "inactive"

    def start(self, service: Service) -> tuple[bool, str]:
        """Start an installed service now, without rewriting it. On launchd a label that is
        not loaded (a stop is a bootout) is bootstrapped from the installed plist, and then,
        loaded either way, kickstarted: the bootstrap alone may start nothing (c-747), and
        of a label already loaded it is only a complaint. A scheduled job is never
        kickstarted, loaded or not (r1.F2): it is bootstrapped when it is not loaded, and
        left to its schedule. systemd starts the primary unit. A service that is running
        is left running by both."""
        self.refuse()
        if self.kind != LAUNCHD:
            return said(systemctl("start", self.primary(service)))
        done = None
        if not self.state(service.label)[0]:
            argv = ["launchctl", "bootstrap", f"gui/{os.getuid()}",
                    str(self.installed_dir / f"{service.label}.plist")]
            done = subprocess.run(argv, capture_output=True, text=True)
        if done is not None and (done.returncode != 0 or service.scheduled):
            return said(done)
        if service.scheduled:
            return True, f"{service.label} is loaded and runs on its schedule"
        code, text = self.kick(service.label)
        return code == 0, text

    def stop(self, service: Service) -> tuple[bool, str]:
        """Stop it and leave it installed. On launchd a KeepAlive agent is restarted by any
        kill, so a stop is a bootout of the label; the plist stays and a login (or `start`)
        brings it back."""
        self.refuse()
        if self.kind == LAUNCHD:
            argv = ["launchctl", "bootout", f"gui/{os.getuid()}/{service.label}"]
            done = subprocess.run(argv, capture_output=True, text=True)
        else:
            done = systemctl("stop", self.primary(service))
        return said(done)

    def restart(self, label: str) -> tuple[bool, str]:
        """Stop and start it in one step, so a KeepAlive service comes back reading its
        inputs afresh (the talker's run dir) rather than bouncing into the old ones."""
        self.refuse()
        if self.kind == LAUNCHD:
            argv = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"]
            done = subprocess.run(argv, capture_output=True, text=True)
        else:
            done = systemctl("restart", f"{label}.service")
        return said(done)


def said(done: subprocess.CompletedProcess) -> tuple[bool, str]:
    """(ok, what to print): the command line when it worked, else what it complained."""
    how = shlex.join(done.args) if isinstance(done.args, list) else str(done.args)
    return done.returncode == 0, how if done.returncode == 0 else (done.stderr or done.stdout or how).strip()


def systemctl(*args: str) -> subprocess.CompletedProcess:
    """`systemctl --user`, with the user manager's address filled in when the shell lacks it
    (`su`, `sudo -u`, cron): the manager runs under /run/user/<uid> once lingering is on."""
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                          env=user_bus_env())


def user_bus_env(run_user: Path = Path("/run/user")) -> dict:
    env = dict(os.environ)
    runtime = run_user / str(os.getuid())
    if not env.get("XDG_RUNTIME_DIR") and runtime.is_dir():
        env["XDG_RUNTIME_DIR"] = str(runtime)
    if not env.get("DBUS_SESSION_BUS_ADDRESS") and (runtime / "bus").exists():
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime / 'bus'}"
    return env


def unit_property(unit_name: str, prop: str) -> str:
    done = systemctl("show", unit_name, f"--property={prop}")
    for line in done.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == prop:
            return value.strip()
    return ""


LINGER_WARNING = ("lingering is OFF for {user}: these units stop at logout and do not start at "
                  "boot. `sudo loginctl enable-linger {user}`")


def lingering(user: str, linger_dir: Path = LINGER_DIR) -> bool:
    """Whether systemd keeps `user`'s manager running with nobody logged in. The flag file
    is what `loginctl enable-linger` writes and what logind reads at boot."""
    return (linger_dir / user).exists()


def linger_report() -> dict:
    """What `keel doctor` prints: on systemd whether this user lingers, elsewhere nothing
    to check (launchd runs a user's agents from login, and the Mac is logged in)."""
    if platform() != SYSTEMD:
        return {"applicable": False}
    user = pwd.getpwuid(os.getuid()).pw_name
    return {"applicable": True, "user": user, "on": lingering(user)}


def installed(label: str, home: Path | None = None) -> bool:
    """A service this machine has installed (its unit or plist is where the manager looks),
    so a service never installed here is not reported as down."""
    manager = Manager(home or Path.home())
    suffix = ".service" if manager.kind == SYSTEMD else ".plist"
    return (manager.installed_dir / f"{label}{suffix}").exists()
