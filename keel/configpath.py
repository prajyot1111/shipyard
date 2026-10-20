"""Which toml a Keel process reads: the one answer, for every process that asks.

`KEEL_CONFIG` names a file outright. Without it the file is the root's own: its
`config.toml` (the install's, gitignored), else an untracked `keel.toml` an older checkout
kept, else the shipped example (`etc/shipyard.example.toml`, c-722 landing B: no one's own
config is tracked any more). `keel/config.py`
loads that file, a service file is told about it (`named`), and the voice gateway, which
reads two tables of it for itself, asks here too (`voice/harbor_voice/config.py`), so the
gateway and the `kb` it runs can never disagree about which file it is.

Stdlib only and nothing of Keel's imported: the voice package (Python 3.12) imports this.
"""

import os
from pathlib import Path

INSTALL_CONFIG = "config.toml"   # the install's own file, gitignored (c-610 S1)
SHIPPED_CONFIG = "keel.toml"     # an older checkout's own config, untracked since c-722
EXAMPLE_CONFIG = "etc/shipyard.example.toml"   # what a checkout with neither reads
CONFIG_ENV = "KEEL_CONFIG"


def config_file(root: Path) -> Path:
    """The file a checkout at `root` reads: its `config.toml`, else its `keel.toml`, else the
    shipped example, whose state is anchored to a home and so is a scratch board."""
    for name in (INSTALL_CONFIG, SHIPPED_CONFIG):
        if (root / name).is_file():
            return root / name
    return root / EXAMPLE_CONFIG


def own_configs(root: Path) -> set[Path]:
    """The files that are the root's own rather than named on purpose."""
    return {(root / name).resolve() for name in (INSTALL_CONFIG, SHIPPED_CONFIG, EXAMPLE_CONFIG)}


def install_of(source, root: Path) -> Path | None:
    """The install a toml belongs to: the directory of an install's own `config.toml`
    outside the code at `root`, else None (a checkout's own config, a scratch or test file)."""
    if not source:
        return None
    source = Path(source).expanduser()
    if source.name != INSTALL_CONFIG or source.parent.resolve() == Path(root).expanduser().resolve():
        return None
    return source.parent


def config_path(root: Path, env: dict | None = None) -> Path:
    """The toml to load for the code at `root`: `KEEL_CONFIG` if set, else `config_file`."""
    override = (os.environ if env is None else env).get(CONFIG_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return config_file(root)


def named(source, root: Path, scratch: bool = False) -> str | None:
    """The toml a child or a service must be handed as `KEEL_CONFIG`, or None when the
    root's own is right.

    A config loaded from a file of its own (an install's `config.toml`, the demo sandbox's)
    is named, because a process started with `KEEL_HOME` alone would load `<root>/keel.toml`
    instead: another board. The root's own file is never passed: a named toml is taken at
    its word, and code running in a Keel worktree must keep getting that worktree's scratch
    board. A scratch config passes nothing, for the same reason.
    """
    if source is None or scratch:
        return None
    source = Path(source).expanduser().resolve()
    return None if source in own_configs(Path(root)) else str(source)


def reads_line(handed: str | None, root: Path) -> str:
    """What an install command says about the service file it wrote: the toml that service
    will read. `handed` is what `named` gave it. Said because an install run with no config
    named succeeds and leaves the service on the checkout's own file, silently otherwise."""
    if handed:
        return f"the service reads {handed}"
    return f"the service reads {config_file(Path(root))}, the checkout's own (no other config was named)"
