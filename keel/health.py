"""One answer to "is Keel healthy": green, amber or red, with a short reason per item.

`verdict` is pure: the facts in, the level and the reasons out. `gather` reads the facts
the doctor reads, the cheap way, and `current` keeps one verdict per minute for the deck,
which puts it on its state document as `health` (`keel/serve.py`, `with_code_state`). The
deck draws it; nothing here pushes it anywhere. `services` reads the same facts per service
(the talker, voice, the drain, the backup) for the deck's services block, and `current`
carries it beside the verdict; the deck also asks for both on `/api/health`, because the
verdict does not move the state's revision.

It exists because every silent failure found on 2026-09-23 had a reading somewhere and no
place that read them together: a talker alive with no session for two days, a talker
stopped for two more, a backup pull dying mid-sleep, a doctor sitting at exit 1 on an
accepted condition so that a new fault was one more line on a report already red.

THE RULES, worst first. Red: a talker fault, a voice gateway installed here and not
answering, a drain with no pass in fifteen minutes or none logged, a backup this machine
writes with no successful run in six hours (the tool's own STALE_HOURS). Amber: a talker
still starting, a drain quiet over five minutes, a nightly pull over 48 hours old (the
tool's PULL_STALE_HOURS), and any fact that could not be read. Amber too: any row of the
Logins list (`keel/logins.py`, c-558) that reads expired or missing, and a Claude login
within two days of its 30 days ending. Red instead of amber for an expired login a served
space's houses run under, because no house of that space can run until he logs it back in
(decision D3). The rows are read, a check is never run from here. The reasons are words,
never ages, so the same state reads the same on every poll.

A service this machine has not installed is not asked (the talker's and the gateway's
installed checks), which is also what keeps the suite off the machine's live processes.
"""

import threading
import time
from datetime import datetime, timezone

from keel import backup, deckstate, logins, service, talker, talkerwatch, voice

GREEN, AMBER, RED = "green", "amber", "red"
RANK = {GREEN: 0, AMBER: 1, RED: 2}
DRAIN_AMBER_SECONDS = 5 * 60
DRAIN_RED_SECONDS = 15 * 60
BACKUP_STALE_HOURS = 6       # bin/keel-backup STALE_HOURS
PULL_STALE_HOURS = 48        # bin/keel-backup PULL_STALE_HOURS
CURRENT_SECONDS = 60         # how long the deck reuses one verdict


# ----- the verdict -----

def talker_item(fact) -> tuple[str, str] | None:
    if fact is None:
        return AMBER, "talker: unknown"
    if not fact.get("ok", True):
        return RED, f"talker: {fact['state']}"
    if fact.get("state") == "starting":
        return AMBER, "talker: starting"
    return None


def voice_item(fact) -> tuple[str, str] | None:
    if fact is None:
        return AMBER, "voice: unknown"
    if fact.get("installed") and not fact.get("ok"):
        return RED, "voice: not answering"
    return None


def drain_item(fact) -> tuple[str, str] | None:
    if fact is None:
        return AMBER, "drain: unknown"
    age = fact.get("age_seconds")
    if age is None:
        return RED, "drain: no pass logged"
    if age > DRAIN_RED_SECONDS:
        return RED, "drain: no pass in over 15 minutes"
    if age > DRAIN_AMBER_SECONDS:
        return AMBER, "drain: no pass in over 5 minutes"
    return None


def backup_items(fact) -> list[tuple[str, str]]:
    if fact is None:
        return [(AMBER, "backup: unknown")]
    found = []
    if fact.get("writes"):
        age = fact.get("success_age")
        if age is None or age > BACKUP_STALE_HOURS * 3600:
            found.append((RED, f"backup: no successful run in over {BACKUP_STALE_HOURS}h"))
    if fact.get("pulls"):
        age = fact.get("pull_age")
        if age is None or age > PULL_STALE_HOURS * 3600:
            found.append((AMBER, f"backup pull: none in over {PULL_STALE_HOURS}h"))
    return found


def login_items(rows) -> list[tuple[str, str]]:
    """One reason per red row of the Logins list: red where a served space's houses run
    under it, amber otherwise; amber for a login about to end. Good, unknown and never
    checked say nothing (an unknown check is never read as expired)."""
    if rows is None:
        return [(AMBER, "logins: unknown")]
    found = []
    for row in rows:
        name = f"{row.get('host')} {row.get('label')}"
        if logins.red(row):
            found.append((RED if row.get("houses") else AMBER, f"login: {name} {row['state']}"))
        elif row.get("ending") and row.get("expires"):
            found.append((AMBER, f"login: {name} ends {row['expires'][:10]}"))
    return found


def verdict(facts: dict) -> dict:
    """`{"level", "reasons"}` from the facts `gather` returns. An absent key is a fact not
    asked for; a key present as None is one that could not be read."""
    items = []
    for key, read in (("talker", talker_item), ("voice", voice_item), ("drain", drain_item)):
        if key in facts:
            items.append(read(facts[key]))
    if "backup" in facts:
        items += backup_items(facts["backup"])
    if "logins" in facts:
        items += login_items(facts["logins"])
    items = [item for item in items if item]
    items.sort(key=lambda item: -RANK[item[0]])
    level = items[0][0] if items else GREEN
    return {"level": level, "reasons": [reason for _level, reason in items]}


# ----- the services block (F4) -----
#
# The same facts read per service rather than folded: one row each for the talker, voice,
# the drain and the backup, with the service's own word for its state, the level the
# verdict gives it, and the INSTANT its age counts from (never an age, so the page keeps
# it current on its own clock between fetches, and the rows read the same on every poll).
# A service this machine does not run says so at level `off`, with no instant.

OFF = "off"
SERVICES = ("talker", "voice", "drain", "backup")


def iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def level_of(item: tuple[str, str] | None) -> str:
    return item[0] if item else GREEN


def unknown() -> dict:
    return {"state": "unknown", "level": AMBER, "at": None}


def talker_row(fact, now: float) -> dict:
    if fact is None:
        return unknown()
    if fact.get("state") == "not-installed":
        return {"state": "not installed here", "level": OFF, "at": None}
    running = fact.get("state") in ("serving", "starting", "no-session", "fault")
    return {"state": fact.get("state"), "level": level_of(talker_item(fact)),
            "at": iso(fact.get("since")) if running else None}


def voice_row(fact, now: float) -> dict:
    if fact is None:
        return unknown()
    if not fact.get("installed"):
        return {"state": "not installed here", "level": OFF, "at": None}
    return {"state": "answering" if fact.get("ok") else "not answering",
            "level": level_of(voice_item(fact)), "at": iso(now)}


def drain_row(fact, now: float) -> dict:
    if fact is None:
        return unknown()
    if fact.get("age_seconds") is None:
        return {"state": "no pass logged", "level": RED, "at": None}
    return {"state": "passing" if fact.get("alive") else "quiet",
            "level": level_of(drain_item(fact)), "at": fact.get("at")}


def backup_row(fact, now: float) -> dict:
    if fact is None:
        return unknown()
    items = backup_items(fact)
    level = max((item[0] for item in items), key=RANK.get, default=GREEN)
    if fact.get("writes"):
        age = fact.get("success_age")
        return {"state": "last good run" if age is not None else "never succeeded",
                "level": level, "at": iso(now - age) if age is not None else None}
    if fact.get("pulls"):
        age = fact.get("pull_age")
        return {"state": "last pull" if age is not None else "never pulled",
                "level": level, "at": iso(now - age) if age is not None else None}
    return {"state": "not set up here", "level": OFF, "at": None}


ROWS = {"talker": talker_row, "voice": voice_row, "drain": drain_row, "backup": backup_row}


def services(facts: dict, now: float) -> list[dict]:
    """`[{name, state, level, at}]`, the four services in a fixed order, from `gather`'s
    facts. `at` is an ISO instant or None; `level` is green, amber, red or `off`."""
    return [dict(ROWS[name](facts.get(name), now), name=name) for name in SERVICES]


# ----- the facts -----

def attempt(read):
    """A fact, or None when reading it raised: an unreadable fact is amber, never a crash."""
    try:
        return read()
    except Exception:  # noqa: BLE001 - a health read must never take the deck down
        return None


def voice_fact(cfg) -> dict:
    installed = service.installed(voice.LABEL, cfg.home)
    return {"installed": installed, "ok": bool(installed and voice.health(cfg.voice_port))}


def backup_fact(cfg, now: float) -> dict:
    paths = backup.paths_from(cfg, home=cfg.home)
    return {"writes": bool(cfg.backup_sets), "pulls": bool(cfg.backup_pull),
            "success_age": backup.state_age(paths, "last_success", now),
            "pull_age": backup.state_age(paths, "last_pull", now)}


def talker_fact(paths, now: float) -> dict:
    """The talker's verdict plus `since`, its last start, which the services row ages from."""
    return dict(talker.health(paths, now), since=talkerwatch.started_at(paths.state_dir))


def gather(cfg, now: float | None = None) -> dict:
    """The facts."""
    now = time.time() if now is None else now
    paths = talker.paths_from(cfg)
    paths.home = cfg.home
    return {
        "talker": attempt(lambda: talker_fact(paths, now)),
        "voice": attempt(lambda: voice_fact(cfg)),
        "drain": attempt(lambda: deckstate.drain_status(cfg)),
        "backup": attempt(lambda: backup_fact(cfg, now)),
        "logins": attempt(lambda: logins.public(cfg)),
    }


# ----- the deck's copy -----

_LOCK = threading.Lock()
_CURRENT: dict = {}


def reading(cfg) -> dict:
    """One fresh reading: the verdict, the services block beside it (F4), and the Logins
    rows (c-558), which the deck's health sheet, Now and the Console draw."""
    at = time.time()
    facts = gather(cfg, at)
    return dict(verdict(facts), services=services(facts, at), logins=facts.get("logins") or [])


def current(cfg) -> dict:
    """The verdict and the services, rebuilt at most once a minute: the deck asks on every
    state fetch and on `/api/health`. Kept per state dir, so two decks in one process (the
    suite) never share one."""
    now, key = time.monotonic(), str(cfg.state_dir)
    with _LOCK:
        kept = _CURRENT.get(key)
        if kept is None or now - kept[1] > CURRENT_SECONDS:
            kept = _CURRENT[key] = (reading(cfg), now)
        return kept[0]
