"""What the Setup view's writes share (c-618): the install a config belongs to, and the one
checked write of its `config.toml` (`keel/configedit.py`).

Every write refuses a config that is not an install's (`appservices.install_dir`: the
`config.toml` of a directory outside the code), so a checkout's own config (an older
checkout's `keel.toml`) is never written from the deck. `keel/onboarding.py` has the view and its verbs.
"""

from __future__ import annotations

import re
from pathlib import Path

from keel import appservices, configedit
from keel import config as config_module
from keel.config import Config

BACKUPS = Path("state") / "config-backups"
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class SetupError(Exception):
    """A setup change that was not made; the message says why."""


def installed(cfg: Config) -> Path | None:
    try:
        return appservices.install_dir(cfg)
    except appservices.NotAnInstall:
        return None


def install_of(cfg: Config) -> Path:
    """The install, or SetupError: Setup writes an install's files only."""
    try:
        return appservices.install_dir(cfg)
    except appservices.NotAnInstall as error:
        raise SetupError(f"Setup edits an install only: {error}") from None


def claude_dir(cfg: Config) -> Path:
    home = installed(cfg)
    return home / "claude" if home else cfg.root / "claude"


def name_of(value: str, what: str) -> str:
    if not NAME.match(value or ""):
        raise SetupError(f"{value!r} is not a {what}: lower case letters, digits, - and _")
    return value


def space_of(cfg: Config, name: str):
    space = cfg.spaces.get(name)
    if space is None:
        raise SetupError(f"there is no space {name!r}; the spaces are {', '.join(sorted(cfg.spaces))}")
    return space


def edit(cfg: Config, change) -> dict:
    """Run `change(text) -> text` on the install's config and write it, checked and backed up."""
    home = install_of(cfg)
    path = Path(cfg.source)
    text = path.read_text()
    try:
        kept = configedit.write(path, text, change(text), home / BACKUPS,
                                lambda p: config_module.load(p, ensure=False))
    except configedit.EditError as error:
        raise SetupError(str(error)) from None
    return {"config": str(path), "backup": str(kept)}
