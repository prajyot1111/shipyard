"""A config change the running deck reads in place (c-729), and the ones that still re-exec it.

Every setup verb that writes `config.toml` (`onboarding.CONFIG_VERBS`: a repo added, attached
or removed, a pack on or off, a settings save, Back up turned on) used to re-exec the deck so
it read the new file. On a fresh install that is nearly every tap of the first run: the
choice of builder, each repo, the plan question, the backup. The page waited out each
restart, and a render in that window drew the setup as not read yet.

Most of the config is read per request from the handler's `cfg` and the deck's, so the deck
loads the file again and swaps it in (`reload`): the handler class's `cfg`, and the deck's
own (`Deck.reread`, which also drops its cache and its kept readings). What the process
bound when it started cannot be swapped: its port and its state (a socket and a database
connection are open on them), and voice, whose gateway reads its environment and whose
holds were set up at start. A change to any of those (`BOUND`, and every `voice_` field) is
answered as before: the deck re-execs once it is quiet (`serve.restart_when_quiet`), and a
voice change reinstalls the gateway first. So does a config that does not load.
"""

from __future__ import annotations

from dataclasses import fields

from keel import config as config_module
from keel import readiness

# What the process holds open or set up from the config when it started.
BOUND = ("root", "state_dir", "db_path", "serve_port", "voice_port",
         "voice_hold_seconds", "source", "host")


def bound_names(cfg) -> list[str]:
    names = [f.name for f in fields(cfg) if f.name.startswith("voice_")]
    return list(dict.fromkeys([*BOUND, *names]))


def bound_changes(old, new) -> list[str]:
    """The fields the process bound at start that differ between `old` and `new`."""
    return [name for name in bound_names(old) if getattr(old, name, None) != getattr(new, name, None)]


def voice_moved(cfg) -> bool:
    """The config file now differs from `cfg` in a voice field (r2.F6): what a verb that wrote
    the config and then failed never says in an answer, so the restart that follows it still
    reinstalls the voice gateway first. A file that does not load says nothing."""
    try:
        new = config_module.load(cfg.source, ensure=False) if cfg.source else None
    except (config_module.ConfigError, OSError, ValueError):
        return False
    return new is not None and any(name.startswith("voice_") for name in bound_changes(cfg, new))


def reload(handler, deck) -> bool:
    """Read the config again and swap it in, unless what the process bound has changed or the
    file does not load: True when the deck now runs on the new config, False when it must
    re-exec. `handler` is the server's bound handler class, whose `cfg` every request reads."""
    old = handler.cfg
    try:
        new = config_module.load(old.source, ensure=False) if old.source else None
    except (config_module.ConfigError, OSError, ValueError):
        return False
    if new is None or bound_changes(old, new):
        return False
    handler.cfg = new
    deck.reread(new)
    readiness.forget()
    return True
