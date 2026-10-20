"""The keys a two-machine config still carries (c-622), read by `keel/config.py`.

Keel runs on one machine, so each of these is ignored and named once in `Config.warnings`
(Now's warning panel, `keel doctor`), never a refusal: an old file always loads. Where one
machine still means what the old key said, it is carried instead, and the warning says so:
the limits of `[hosts.<this host>]` fill what `[keel]` leaves out (`host_limits`), as its
backup keys fill `[backup]` (`config.backup_keys`).

`[console]` is Bosun's: a `[console] host` naming another machine is read as this one, so
Bosun runs here rather than every Console tap being refused (`console_host`). Its
`board_url`, `config_dir` and `checkout` made Bosun its own Unix user, whose `kb` reached the
board over HTTP; that mode is retired (c-648), so the three are dropped and named.
"""

import os

from keel import settings

RETIRED_TABLES = ("hosts", "tenancy")
RETIRED_KEEL_KEYS = ("board_url",)
RETIRED_SPACE_KEYS = ("host",)
# The environment the two-machine Keel read: `KEEL_HOST` named this machine's host table,
# `KEEL_URL` sent `kb` to a board over HTTP.
RETIRED_ENV = ("KEEL_HOST", "KEEL_URL")
# `[console]`: the keys that made Bosun its own Unix user (the board its `kb` reached, its
# config dir, its checkout). Dropped and named: nothing reads them (c-648).
CONSOLE_OWN_USER = ("board_url", "config_dir", "checkout")
# What `[hosts.<this host>]` held that one machine still means: its limits.
HOST_LIMITS = ("houses_max", "reviews_max") + settings.KEEL_LIMITS
ONE_MACHINE = "Shipyard runs on one machine now (c-622), so it is ignored"
OWN_USER = ("Bosun as its own Unix user is retired (c-648): it runs as the user Shipyard runs "
            "as, so it is ignored")


def retired(data: dict) -> tuple[dict, list[str]]:
    """The toml without its two-machine keys, and one warning per key it dropped. The
    `[hosts.<this host>]` backup keys and limits still count (`config.backup_keys`,
    `host_limits`), read from the raw toml."""
    data, notes = dict(data), []
    for table in RETIRED_TABLES:
        if table in data:
            data.pop(table)
            notes.append(f"[{table}]: {ONE_MACHINE}")
    for table in ("keel", "machine"):
        if table in data:
            data[table], said = dropped(data[table], RETIRED_KEEL_KEYS, f"[{table}]")
            notes += said
    spaces = {}
    for name, space in (data.get("spaces") or {}).items():
        spaces[name], said = dropped(space, RETIRED_SPACE_KEYS, f"[spaces.{name}]")
        notes += said
    if spaces:
        data["spaces"] = spaces
    if "console" in data:
        gone = [key for key in CONSOLE_OWN_USER if key in data["console"]]
        data["console"] = {key: value for key, value in data["console"].items()
                           if key not in gone}
        notes += [f"[console] {key}: {OWN_USER}" for key in gone]
    return data, notes


def dropped(table: dict, keys: tuple, where: str) -> tuple[dict, list[str]]:
    table = dict(table or {})
    gone = [key for key in keys if key in table]
    for key in gone:
        table.pop(key)
    return table, [f"{where} {key}: {ONE_MACHINE}" for key in gone]


def env_notes(environ=os.environ) -> list[str]:
    """One line per retired variable set in the environment: nothing reads it now."""
    return [f"{name} is set in the environment: {ONE_MACHINE} (unset it)"
            for name in RETIRED_ENV if environ.get(name)]


def host_limits(raw: dict, keel: dict, host: str) -> tuple[dict, list[str]]:
    """`[keel]` with the limits of the old `[hosts.<this host>]` table filled in where it
    leaves one out (`[keel]` wins, as `[backup]` does over its backup keys), and one line
    per limit carried, naming it."""
    mine = (raw.get("hosts") or {}).get(host) or {}
    carried = {key: mine[key] for key in HOST_LIMITS if key in mine and key not in keel}
    return {**keel, **carried}, [f"[hosts.{host}] {key} = {value}: carried as [keel] {key}, "
                                 f"as Shipyard runs on one machine now (c-622); move it there"
                                 for key, value in carried.items()]


def console_host(data: dict, host: str) -> tuple[dict, list[str]]:
    """`[console]` whose `host` names another machine, read as this one: on one machine
    Bosun runs here, on an install's config and on any other alike (review r1.D1)."""
    console = dict(data.get("console") or {})
    named = console.get("host")
    if not named or str(named) == host:
        return data, []
    console["host"] = host
    return {**data, "console": console}, [
        f"[console] host names {named}, not this machine ({host}): {ONE_MACHINE}"]
