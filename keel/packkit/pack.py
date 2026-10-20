"""Which pack the kit is running for: its folder, its host layer and its words.

A verb's shim binds its own pack once (`bind(<the pack's folder>, <its layer's module>)`),
so the kit knows the folder by the shim, never by where the kit's own files are: the guard's
own-verb test, the brief's `pr` path and `ship mine`'s spaces are keyed to the pack. One
process runs one pack, so the binding is the process's; a pack's tests bind theirs in their
suite fence, and `bind` again replaces it.

The words (`words()`) are the pack's `[terms]` (what it calls a change) and its host's name,
so the kit's sentences say "pull request" or "merge request" as the pack does, and spell no
noun of their own.
"""

import importlib
import sys
import tomllib
from pathlib import Path

from keel.packkit.errors import HostError
from keel.packkit.layer import check_layer

TERMS = ("change", "changes", "change_short", "changes_short")


class Bound:
    """One pack, bound: `dir`, `layer` (the module), `host` (its `HostConfig`), `terms`."""

    def __init__(self, folder: Path, layer, terms: dict):
        self.dir, self.layer, self.host, self.terms = folder, layer, layer.HOST, terms


class Words:
    """The pack's words for a change, and its host's: `change`, `changes`, `short`, `shorts`,
    `host` and `on` ("on GitHub")."""

    def __init__(self, terms: dict, host):
        self.change, self.changes = terms["change"], terms["changes"]
        self.short, self.shorts = terms["change_short"], terms["changes_short"]
        self.host, self.on = host.name, host.on

    def fill(self) -> dict:
        """For a template: `{change}`, `{changes}`, `{short}`, `{shorts}`, `{host}`, `{on}`."""
        return {"change": self.change, "changes": self.changes, "short": self.short, "shorts": self.shorts,
                "host": self.host, "on": self.on}


_bound: Bound | None = None


def terms_of(folder: Path) -> dict:
    """The pack's `[terms]` for a change, over the engine's own defaults (`keel/terms.py`)."""
    from keel.terms import DEFAULTS  # noqa: PLC0415 - read once, when a pack is bound
    try:
        found = tomllib.loads((Path(folder) / "pack.toml").read_text(encoding="utf-8")).get("terms") or {}
    except (OSError, ValueError):
        found = {}
    return {key: str(found.get(key) or DEFAULTS[key]) for key in TERMS}


def bind(folder, layer: str) -> Bound:
    """Run the kit for the pack in `folder`, whose host layer is the module `layer` there."""
    global _bound
    folder = Path(folder).resolve()
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    module = importlib.import_module(layer)
    check_layer(module, layer)
    _bound = Bound(folder, module, terms_of(folder))
    return _bound


def current() -> Bound:
    if _bound is None:
        raise HostError("no pack is bound: a verb's shim binds its own pack first")
    return _bound


def here() -> Path:
    return current().dir


def layer():
    return current().layer


def host():
    return current().host


def words() -> Words:
    bound = current()
    return Words(bound.terms, bound.host)
