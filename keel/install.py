"""`keel install`: the engine's service for `keel run`, loaded only when asked.

On macOS that is the launchd agent `dev.keel.plist`; on Linux the systemd user unit
`dev.keel.service`, rendered into `Config.services_dir` (the install's `services/`, a bare
checkout's `etc/`; `keel/service.py` renders either). `--load` copies it where the
manager looks and starts it; without the flag nothing on the machine changes. The service
restarts whenever it exits, gets a PATH that reaches `claude` and `python3`, `KEEL_HOME`,
`KEEL_CONFIG` when the config it was rendered from is not the checkout's own
(`config.named_env`), and logs under `state/logs/`.

Two Linux-only settings, both about the houses. The drain's `claude --bg` calls start the
harness's background daemon when none is running, and on Linux a process stays in the
cgroup of the unit that started it however it detaches, so then the daemon and every
house it runs live in this unit:
- `KillMode=process`: a restart or stop of the engine ends only `keel run`. The default
  would end every house with it, and nothing automatic may end a live session.
- `CPUWeight=100`, the default, written down so the voice gateway's higher weight
  (`keel/voice.py`) has something to be higher than: nice orders processes only inside
  one cgroup (docs/atlas/30-drain.md, "Voice ahead of houses").
"""

import os
from pathlib import Path

from keel import config as config_module
from keel import service as service_module
from keel.config import Config

LABEL = "dev.keel"
DEFAULT_ROLES = "drain,serve,fetch"
PATH_ENTRIES = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
ENGINE_CPU_WEIGHT = 100


def launchd_path(home: Path | None = None) -> str:
    home = home or Path.home()
    return os.pathsep.join(str(home / entry[2:]) if entry.startswith("~/") else entry
                           for entry in PATH_ENTRIES)


def service(cfg: Config, roles: str = DEFAULT_ROLES, home: Path | None = None) -> service_module.Service:
    logs = cfg.logs_dir
    return service_module.Service(
        label=LABEL,
        description="Keel: " + roles,
        argv=[str(cfg.root / "bin" / "keel"), "run", "--roles", roles],
        cwd=cfg.root,
        # The config it was rendered from, when that is not the checkout's own (c-711).
        env={"KEEL_HOME": str(cfg.root), **config_module.named_env(cfg), "PATH": launchd_path(home)},
        stdout=logs / "keel.out.log",
        stderr=logs / "keel.err.log",
        kill_mode="process",
        cpu_weight=ENGINE_CPU_WEIGHT,
    )


def plist_text(cfg: Config, roles: str = DEFAULT_ROLES) -> str:
    return service_module.plist(service(cfg, roles)).decode()


def write(cfg: Config, roles: str = DEFAULT_ROLES, manager: service_module.Manager | None = None) -> list[Path]:
    """Render the engine's service into `cfg.services_dir` (the install's `services/`, or a
    bare checkout's `etc/`, c-722), and make sure the log directory exists."""
    manager = manager or service_module.Manager(Path.home())
    return manager.write(service(cfg, roles, manager.home), cfg.services_dir)


def load(cfg: Config, roles: str = DEFAULT_ROLES, manager: service_module.Manager | None = None) -> int:
    """Copy it where the service manager looks and start it (the human's step)."""
    manager = manager or service_module.Manager(Path.home())
    return manager.load(service(cfg, roles, manager.home), cfg.services_dir)
