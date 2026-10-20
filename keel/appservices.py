"""`shipyard service install|start|stop|status|uninstall`: an install's deck, drain and fetch.

An install made by `shipyard init` (`keel/installer.py`) runs as three services of the user
who made it, through the one interface in `keel/service.py`: launchd LaunchAgents on macOS,
systemd user units on Linux, and a refusal anywhere else.

- **deck**: `keel run --roles serve`, the deck on the install's `serve_port`.
- **drain**: `keel run --roles drain`, which starts and recovers the houses.
- **fetch**: `keel run --roles fetch`, which runs the segments' fetchers, turns their asks
  into cards and files the recurring cards (`keel/fetch.py`, c-742).

Three processes rather than the engine's one (`keel/install.py`), so the deck can be
restarted without touching the drain, a slow or failing fetcher never holds up a pass of
the drain, and each can be stopped from here alone. Each gets
`KEEL_CONFIG=<install>/config.toml` (the install's own file; `KEEL_HOME` stays the code it
runs from, `docs/atlas/88-install.md` says why) and logs under the install's `state/logs/`.
The deck and the drain keep `KillMode=process` on Linux for the engine's reason: a house's
`claude --bg` daemon lives in the cgroup of the unit that started it, and nothing automatic
ends a live session. The fetch role starts no house, so its unit keeps systemd's default,
and a stop ends the fetcher it was running with it.

The units are rendered into `<install>/services/` and, on `install`, copied where the
manager looks. `install` writes and (re)starts only what is missing, changed or not running:
a service whose installed unit is the one it would write, and which is running, is left
running, so adding one never restarts the others. `--dry-run` prints every file it would
write and every command it would run, and changes nothing. The labels are fixed
(`dev.shipyard.deck`, `dev.shipyard.drain`, `dev.shipyard.fetch`), so a user has one install
with services; a second install runs by hand (`shipyard serve`).

**An install made before a service existed gets it without a hand step** (`bring_up`, c-742):
the drain calls it when it starts, which is what a deploy restarts, and it installs a
service the install NEVER HAD, only while the drain's own unit where the manager looks runs
this install. "Never had" is read off the install's own `services/` folder: `install`
renders a unit there and `uninstall` keeps that copy, so a service with a rendered unit is
one its owner installed and perhaps took down on purpose, and the drain leaves it alone
(a drain start is every deploy, every config save and every packs move). Only a service
added since installs were first made is brought up (`ADDED_LATER`), never the deck or the
drain. It never rewrites or restarts a service that is installed.

**"Started" is said of a service that has a process** (c-747). The manager taking a load or
a start is not that: launchd loaded the fetch service on 2026-10-11 and held its start
back, with no process and no log, while the drain's log said "installed and started". So
`install`, `start` and the bring-up wait a short, bounded time for a pid (`settled`,
`service.Manager.running`), and with none say so and fail. A bring-up left that way stays
installed, with a note beside its rendered unit (`pending`), and the next drain start
starts it rather than installing it again; the note goes when a process is seen, or when
the owner has the manager load, start, stop or uninstall it (`in_hand`; a refused verb
asked for nothing and leaves it), so a stop is never undone.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from keel import config as config_module
from keel import drainprobe, install, service as service_module
from keel.config import Config

PREFIX = "dev.shipyard"
ROLES = {"deck": "serve", "drain": "drain", "fetch": "fetch"}
# The services that start houses: a stop of one must leave the harness's daemon alive.
HOUSE_STARTERS = ("deck", "drain")
# The services an install made before them lacks, which the drain brings up as it starts
# (`bring_up`). The deck and the drain are what every install was made with: one of those
# missing was taken down, or never wanted, by its owner.
ADDED_LATER = ("fetch",)
VERBS = ("install", "start", "stop", "status", "uninstall")
# Beside a service's rendered unit in the install's `services/`: this bring-up loaded it and
# has not seen it run. It is what tells that service from one its owner stopped, which on
# systemd reads the same (enabled, no pid), so only the first is started at a drain start.
# A file and not a row of the board, as the rendered unit beside it is: it is a fact about
# this machine's service manager, not about any card (the decision, r1.F6, is in
# `docs/atlas/88-install.md`).
UNSTARTED = ".unstarted"
# The note's one line: how many drain starts have tried to start it since, then words for
# whoever opens it. The drain tries at this many starts and then stops (r1.F5).
NOTE = "{tried} drain starts have tried to start it; loaded by the drain's bring-up, no process seen yet\n"
OWED_STARTS = 3


class NotAnInstall(Exception):
    pass


def install_dir(cfg: Config) -> Path:
    """The install this config belongs to: the directory of its `config.toml`."""
    source = Path(cfg.source) if cfg.source else None
    if source is None or source.name != config_module.INSTALL_CONFIG or source.parent == cfg.root:
        raise NotAnInstall(f"{source} is not an install's config; run `shipyard init <dir>` "
                           f"first, then `<dir>/bin/shipyard service ...`")
    return source.parent


def service_path(home: Path) -> str:
    """The engine's fixed PATH, led by the folder `claude` is in on this shell's PATH (nvm,
    npm-global, ~/.claude/local), so the drain finds the claude the prerequisite check found."""
    fixed = install.launchd_path(home)
    found = shutil.which("claude")
    folder = str(Path(found).parent) if found else None
    return fixed if not folder or folder in fixed.split(os.pathsep) else folder + os.pathsep + fixed


def foreign_owner(manager: service_module.Manager, item: service_module.Service,
                  config: Path) -> str | None:
    """The other install an installed unit of this label runs, if any: the labels are fixed,
    so a second `shipyard init` would otherwise take the first one's services over."""
    for name in manager.files(item):
        path = manager.installed_dir / name
        text = path.read_text(errors="replace") if path.exists() else ""
        if text and "KEEL_CONFIG" in text and str(config) not in text:
            return str(path)
    return None


def services(cfg: Config, home: Path | None = None) -> list[service_module.Service]:
    home = home or Path.home()
    where = install_dir(cfg)
    keel = cfg.root / "bin" / "keel"
    return [service_module.Service(
        label=f"{PREFIX}.{name}",
        description=f"Shipyard {name} ({where})",
        argv=[sys.executable, str(keel), "run", "--roles", role],
        cwd=cfg.root,
        env={"KEEL_CONFIG": str(where / config_module.INSTALL_CONFIG), "KEEL_HOME": str(cfg.root),
             "PATH": service_path(home)},
        stdout=cfg.logs_dir / f"{name}.out.log",
        stderr=cfg.logs_dir / f"{name}.err.log",
        kill_mode="process" if name in HOUSE_STARTERS else None,
        cpu_weight=install.ENGINE_CPU_WEIGHT,
    ) for name, role in ROLES.items()]


def label(name: str) -> str:
    return f"{PREFIX}.{name}"


def current(manager: service_module.Manager, item: service_module.Service) -> int | None:
    """The pid of a service there is nothing to do for, so `install` leaves it running: the
    unit where the manager looks is the one `install` would write, and it is RUNNING. Loaded
    is not enough (r1.F4): on systemd a stopped unit stays enabled, which `state` reads as
    loaded, and `install` is the command the doctor names for a role that is not running."""
    same = all((manager.installed_dir / name).is_file()
               and (manager.installed_dir / name).read_bytes() == content
               for name, content in manager.files(item).items())
    loaded, pid = manager.state(item.label) if same else (False, None)
    return pid if loaded else None


def kept(cfg: Config, manager: service_module.Manager) -> list[service_module.Service]:
    """The install's services, while the drain's unit where the manager looks runs THIS
    install: the only install a drain start may bring a service up for. None off an install,
    on a system with no manager, on an install that runs by hand (`--no-services`), or where
    another install has the labels."""
    try:
        where = install_dir(cfg)
        items = services(cfg, manager.home)
        drain = next(item for item in items if item.label == label("drain"))
        units = [manager.installed_dir / name for name in manager.files(drain)]
    except (NotAnInstall, service_module.Unsupported):
        return []
    config = str(where / config_module.INSTALL_CONFIG)
    held = all(path.is_file() and config in path.read_text(errors="replace") for path in units)
    return items if held else []


def missing(cfg: Config, manager: service_module.Manager) -> list[service_module.Service]:
    """The services this install never had (`ADDED_LATER`, with no unit rendered in the
    install's own `services/` and none where the manager looks), on an install the drain
    may bring one up for (`kept`). A service the owner uninstalled keeps its rendered unit,
    so it is not one of these (r1.F1)."""
    items = kept(cfg, manager)
    folders = (install_dir(cfg) / "services", manager.installed_dir) if items else ()
    return [item for item in items if item.label in map(label, ADDED_LATER)
            and not any((folder / name).exists() for name in manager.files(item) for folder in folders)]


def pending(cfg: Config, item: service_module.Service) -> Path:
    """The note that a bring-up loaded this service and has not seen it run (`UNSTARTED`)."""
    return install_dir(cfg) / "services" / f"{item.label}{UNSTARTED}"


def unstarted(cfg: Config, manager: service_module.Manager) -> list[service_module.Service]:
    """The services an earlier bring-up loaded and never saw run, which nobody has taken in
    hand since (`act` removes the note): what a drain start starts, and does not reinstall."""
    return [item for item in kept(cfg, manager) if pending(cfg, item).exists()]


def no_process(manager: service_module.Manager, item: service_module.Service) -> str:
    """What is true of a service the manager took and is not running."""
    waited = service_module.START_TRIES * service_module.START_WAIT
    return (f"{manager.kind} loaded it and no process was running after {waited:g} seconds "
            f"({item.stderr} may say why)")


def owed_starts(cfg: Config, item: service_module.Service) -> int:
    """How many drain starts have tried to start it, as the note counts them; 0 for a note
    nothing can be read from."""
    try:
        return int(pending(cfg, item).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


class BringUpFailed(Exception):
    """A missing service could not be installed and started: the drain's failed step."""


def forget(manager: service_module.Manager, item: service_module.Service, etc: Path) -> None:
    """Take back a bring-up that did not start: the manager's own uninstall (the copy it
    reads, and on systemd the unit disabled, so no half-enabled unit is left), then the
    rendered copy, so the install still reads as never having had the service (`missing`)
    and the next drain start tries again. Both copies go even when the uninstall itself
    raises (no service manager at all, r2.F2): one left behind would read as a service the
    install has, and never be tried again."""
    try:
        manager.unload(item)
    finally:
        for name in manager.files(item):
            for folder in (manager.installed_dir, etc):
                (folder / name).unlink(missing_ok=True)


def fetch_held(cfg: Config, item: service_module.Service, own: int | None) -> str | None:
    """Why the fetch service may not be installed or started now, or None: the fetch role
    already runs for this install as another process (`drainprobe.fetch_pids`; `own` is the
    service's own pid, which is not another). Two roles would each file what a pass files.
    The filing lock (`fetchloop.file_cards`) holds that too; this keeps the second from
    starting at all, as the drain's own refusal does (r1.F3)."""
    if item.label != label("fetch"):
        return None
    pids = [pid for pid in drainprobe.fetch_pids(install_dir(cfg) / config_module.INSTALL_CONFIG)
            if pid != own]
    if not pids:
        return None
    return (f"the fetch role already runs for this install as pid {', '.join(map(str, pids))}, "
            f"and two would each file what a pass files; stop it (`kill {pids[0]}`), then "
            f"`shipyard service install fetch`")


BROUGHT, STARTED, FAILED, HELD = "brought", "started", "failed", "held"


def seen(cfg: Config, manager: service_module.Manager, item: service_module.Service) -> int | None:
    """The pid of a service the bring-up just loaded or started, waited for
    (`service.Manager.running`); seeing one ends the retry (`pending`)."""
    pid = manager.running(item.label)
    if pid:
        pending(cfg, item).unlink(missing_ok=True)
    return pid


def install_missing(cfg: Config, manager: service_module.Manager,
                    item: service_module.Service) -> tuple[str, str]:
    """One service the install never had, installed and started: what came of it, and the
    label (brought up) or the sentence for the drain's log.

    A load that fails returns a code and raises nothing (launchd's "Bootstrap failed: 5",
    systemd with no user bus), AFTER the unit was copied where the manager looks
    (`service.Manager.load`). Left there it would read as a service the install has, so it
    is taken back (`forget`), on a raise too, and the next start tries again (r1.F2). A
    load the manager TOOK that gave no process (c-747) is not taken back: the service is
    installed and loaded, so it is noted (`pending`) for the next start to start."""
    why = fetch_held(cfg, item, own=None)       # it has no service, so no pid is its own
    if why:
        return HELD, f"service {item.label} not brought up: {why}"
    etc = install_dir(cfg) / "services"
    code = None
    try:
        manager.write(item, etc)
        code = manager.load(item, etc)
    finally:
        if code != 0:
            forget(manager, item, etc)
    if code != 0:
        return FAILED, (f"service {item.label} was missing and could not be installed and "
                        f"started (exit {code}); the next drain start tries again")
    pending(cfg, item).write_text(NOTE.format(tried=0))
    if seen(cfg, manager, item):
        return BROUGHT, item.label
    return FAILED, (f"service {item.label} was missing and is installed, but not started: "
                    f"{no_process(manager, item)}; the next drain start starts it")


def start_loaded(cfg: Config, manager: service_module.Manager,
                 item: service_module.Service) -> tuple[str, str] | None:
    """One service an earlier bring-up loaded and never saw run (`unstarted`): started, and
    never reinstalled. Nothing is done, and the note goes, for one that runs by now (launchd
    ran it after all, or a login did), that is no longer loaded (taken down since), or that
    the manager says was stopped (`service.Manager.resting`, r1.F4: on systemd a `systemctl
    --user stop` leaves the unit enabled with no pid and goes through no verb of ours)."""
    loaded, pid = manager.state(item.label)
    if pid or not loaded or manager.resting(item):
        pending(cfg, item).unlink(missing_ok=True)
        return None
    why = fetch_held(cfg, item, own=None)
    if why:
        return HELD, f"service {item.label} not started: {why}"
    ok, said = manager.start(item)
    if ok and seen(cfg, manager, item):
        return STARTED, item.label
    return FAILED, gave_no_process(cfg, item, no_process(manager, item) if ok else said)


def gave_no_process(cfg: Config, item: service_module.Service, why: str) -> str:
    """The sentence for an owed start that gave no process, counted in the note. The drain
    makes it at `OWED_STARTS` drain starts and no more (r1.F5): a service that never holds
    a process would otherwise cost every start (each deploy, each config save) the whole
    wait and a failed step. The last one says so, names the command, and drops the note."""
    tried = owed_starts(cfg, item) + 1
    if tried >= OWED_STARTS:
        pending(cfg, item).unlink(missing_ok=True)
        name = item.label.rsplit(".", 1)[-1]
        return (f"service {item.label} is loaded and had no process at {OWED_STARTS} drain starts: "
                f"{why}; the drain stops trying: `shipyard service start {name}` starts it")
    pending(cfg, item).write_text(NOTE.format(tried=tried))
    return (f"service {item.label} is loaded and still has no process: {why}; "
            f"the next drain start tries again ({tried} of {OWED_STARTS})")


def bring_up(cfg: Config, manager: service_module.Manager | None = None) -> dict[str, list[str]]:
    """Install and start every service this install never had (`missing`), start every one
    an earlier bring-up loaded and never saw run (`unstarted`), and nothing else. The
    answer, by what came of each: `brought` (labels installed and seen running), `started`
    (labels started this time), `failed` (a sentence for each with no process) and `held`
    (a sentence for each held back because the fetch role already runs by hand). The drain
    calls it when it starts, so an install made before a service existed gets it at its
    next deploy (c-742)."""
    manager = manager or service_module.Manager(Path.home())
    found: dict[str, list[str]] = {BROUGHT: [], STARTED: [], FAILED: [], HELD: []}
    again = unstarted(cfg, manager)             # read first: what THIS start loads is not retried in it
    outcomes = [install_missing(cfg, manager, item) for item in missing(cfg, manager)]
    outcomes += [start_loaded(cfg, manager, item) for item in again]
    for kind, text in filter(None, outcomes):
        found[kind].append(text)
    return found


def upkeep(cfg: Config, log, failed, manager: service_module.Manager | None = None) -> list[str]:
    """The drain's one call as it starts (`drain.run`): `bring_up`, each service brought up
    or started said through `log(text)`, the drain's log, and only once it has a process
    (c-747). A deploy restarts the drain onto the new code, so this is how an install made
    before a service existed gets it with no hand step. It never fails the start: a service
    with no process, and anything raised, goes to `failed(name)`, the drain's failed step
    (its traceback to the log, and a sighting), and is tried once more at the next start,
    never every pass. Returns the labels that now run because of this call."""
    running: list[str] = []
    try:
        found = bring_up(cfg, manager)
        running = found[BROUGHT] + found[STARTED]
        for name in found[BROUGHT]:
            log(f"service {name} was missing: installed and started")
        for name in found[STARTED]:
            log(f"service {name} was loaded and not running: started")
        for line in found[HELD]:
            log(line)
        if found[FAILED]:
            raise BringUpFailed("; ".join(found[FAILED]))
    except Exception:  # noqa: BLE001 - a missing service is not a reason to run no drain
        failed("service upkeep")
    return running


def counted(names: list[str]) -> str:
    """"2 installed segments (daybook, oci)": how a fetch role that is not running is said,
    here and by the doctor."""
    return f"{len(names)} installed segment{'' if len(names) == 1 else 's'} ({', '.join(names)})"


def status_line(cfg: Config, item: service_module.Service, loaded: bool, pid: int | None) -> str:
    """One service's line, and under the fetch role's, when it is not running, the installed
    segments nothing fetches, with the command that starts it: `install`, whether the unit
    is missing or loaded with no pid, since it starts whatever is not running (`current`),
    where `start` needs the unit installed (r2.F1). The doctor names the same command."""
    # `setupconfig` imports this module and the board's own imports reach `setupconfig`, so
    # the fetch role (which imports the board) is read here, never at import.
    from keel import fetch     # noqa: PLC0415
    line = (f"{item.label}: {'installed' if loaded else 'not installed'}"
            + (f", running as pid {pid}" if pid else (", not running" if loaded else "")))
    names = [path.name for path in fetch.fetchers(cfg)] if item.label == label("fetch") and not pid else []
    if names:
        line += f"\n  nothing fetches {counted(names)}: `shipyard service install fetch`"
    return line


def dry_run(manager: service_module.Manager, items: list[service_module.Service], verb: str) -> int:
    for item in items:
        if verb == "install":
            for name, content in manager.files(item).items():
                print(f"--- would write {manager.installed_dir / name}")
                print(content.decode().rstrip())
        print(f"would {verb} {manager.primary(item)} ({manager.kind})")
    if manager.kind == service_module.SYSTEMD and verb == "install":
        print("lingering: units stop at logout unless `sudo loginctl enable-linger $USER`")
    return 0


def refused(cfg: Config, verb: str, manager: service_module.Manager, item: service_module.Service) -> bool:
    """`install` or `start` of the fetch service beside a fetch role that already runs
    (`fetch_held`): said, and not done."""
    why = fetch_held(cfg, item, manager.state(item.label)[1]) if item.label == label("fetch") else None
    if why:
        print(f"{item.label}: refused: {why}", file=sys.stderr)
    return bool(why)


def settled(manager: service_module.Manager, item: service_module.Service) -> int:
    """After an `install` or a `start` the manager took: "started" is said only once it
    reports a process, waited for a short, bounded time (`service.Manager.running`); with
    none that is said plainly and the exit is non-zero (c-747)."""
    pid = manager.running(item.label)
    if pid:
        print(f"{item.label}: started, running as pid {pid}")
        return 0
    name = item.label.rsplit(".", 1)[-1]
    print(f"{item.label}: not running: {no_process(manager, item)}; "
          f"`shipyard service start {name}` tries again", file=sys.stderr)
    return 1


def in_hand(cfg: Config, item: service_module.Service) -> None:
    """The owner is asking the manager to load, start, stop or uninstall this service, so
    the drain owes it nothing more: the bring-up's note goes (`pending`). Only on a branch
    that acts (r1.F3): a verb that was refused asked the manager for nothing, and the
    start the drain owes is still owed."""
    pending(cfg, item).unlink(missing_ok=True)


def install_one(cfg: Config, manager: service_module.Manager, item: service_module.Service) -> int:
    """`install` of one service: refused where another install has the label, left alone
    where it is current and running (`current`), else written, loaded and waited for."""
    other = foreign_owner(manager, item, install_dir(cfg) / config_module.INSTALL_CONFIG)
    if other:
        print(f"{item.label}: {other} runs another install; `shipyard service uninstall` "
              f"there first (one install per user has services)", file=sys.stderr)
        return 1
    pid = current(manager, item)
    if pid:
        print(f"{item.label}: already installed and running as pid {pid}, left running")
        return 0
    in_hand(cfg, item)
    manager.write(item, install_dir(cfg) / "services")
    return manager.load(item, install_dir(cfg) / "services") or settled(manager, item)


def act(cfg: Config, verb: str, manager: service_module.Manager, only: str | None = None) -> int:
    items = [item for item in services(cfg, manager.home)
             if only is None or item.label.endswith("." + only)]
    code = 0
    for item in items:
        if verb in ("install", "start") and refused(cfg, verb, manager, item):
            code |= 1
        elif verb == "install":
            code |= install_one(cfg, manager, item)
        elif verb == "uninstall":
            in_hand(cfg, item)
            for path in manager.unload(item):
                print(f"removed {path}")
        elif verb in ("start", "stop"):
            in_hand(cfg, item)
            ok, said = getattr(manager, verb)(item)
            print(f"{item.label}: {said}")
            code |= 0 if ok and (verb == "stop" or settled(manager, item) == 0) else 1
        else:
            print(status_line(cfg, item, *manager.state(item.label)))
    return code


def run(cfg: Config, verb: str, dry: bool = False, only: str | None = None,
        manager: service_module.Manager | None = None) -> int:
    manager = manager or service_module.Manager(Path.home())
    if dry:
        items = [item for item in services(cfg, manager.home)
                 if only is None or item.label.endswith("." + only)]
        return dry_run(manager, items, verb)
    if verb in ("install", "start") and only in (None, "drain"):
        why = drainprobe.refusal(install_dir(cfg) / config_module.INSTALL_CONFIG)
        if why:
            print(f"shipyard service {verb}: refused: {why}", file=sys.stderr)
            return 1
    return act(cfg, verb, manager, only)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="shipyard service",
                                     description="the install's deck, drain and fetch role as services")
    parser.add_argument("verb", choices=VERBS)
    parser.add_argument("which", nargs="?", choices=tuple(ROLES), help="one of them (default all)")
    parser.add_argument("--dry-run", action="store_true", help="print what it would write and run")
    args = parser.parse_args(argv)
    try:
        cfg = config_module.load()
        return run(cfg, args.verb, args.dry_run, args.which)
    except (NotAnInstall, service_module.Unsupported, config_module.ConfigError) as refusal:
        print(f"shipyard service: {refusal}", file=sys.stderr)
        return 1
