"""The Logins list: one row per credential Keel depends on, on this machine, with its state,
when it was last checked, and the one-liner that logs it back in (c-558).

On 2026-09-27 a voice turn failed with "OAuth session expired and could not be refreshed"
while the deck's health stayed green: the only login Keel read was the probe of a space the
box's drain serves (`keel/login.py`), kept on the box, and the credential behind that turn
was none of those. This module is the list the deck, the Console and the ask read instead.

**The rows** (`specs`), each built by the machine the credential lives on:

- one per distinct Claude config dir this machine uses: its served spaces' dirs (houses
  depend on these, `houses`), the talker's dir where the talker is installed (it is also
  the voice gateway's), and Bosun's where `[console] host` is this machine;
- `drive`, the backup store's rclone login, where the store is rclone;
- `google-tts` and `jev`, the voice keys, where the voice gateway is installed;
- whatever an adapter's optional `logins` verb returns, under `<space>:<its id>`.

**State from events first.** `saw` marks a Claude dir's row expired the moment a turn that
ran under it prints the harness's words for a lost login (`login.names_login`), and `mark`
is the same for any row from a script (`keel logins mark`, which `bin/keel-backup` calls on
a refused store). The voice gateway and the talker mark through `saw_at`, `mark_at` and
`unmark_at`, into the state dir they already know, never a config they would have to load.
A mark newer than the last check wins until a check settles it: a good one drops it, a red
one confirms it, and an `unknown` one does neither, so the row stays red and is checked again
at `RED_EVERY` (c-560). A key's good check settles nothing either, since it only sees that
the key is there: the gateway's next success takes that mark off.

**Then a cheap check** (`keel/loginprobe.py`), from the drain's pass (`upkeep`): at most
`PROBES_PER_PASS` rows, each due when it was never checked, its check is a day old, it was
marked since, it still holds a mark its last check settled (the hold's probe settles one
too, but only this list's check drops it), or it has been red for `RED_EVERY`. A Claude dir's check is the one-word
haiku probe, which costs nothing when the login is gone, so a red dir is asked often and a
good one daily: never a paid turn every pass.

**Where the answers are kept.** A served space's dir keeps its answer in `login.json`,
which the drain's login hold already reads (`keel/loginhold.py`), so a space has one kept
answer, not two (a dir with no login is kept there as `expired`, the hold's word for it);
every other row keeps its answer, its mark and when it was last seen good
in `state/logins.json`. Both are readings of the machine like the drain log, never board
state.
"""

import argparse
import contextlib
import fcntl
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from keel import atomicfile, login, loginprobe
from keel.loginprobe import EXPIRED, GOOD, MISSING, UNKNOWN

FILE = "logins.json"
DAY = 24 * 3600
RED_EVERY = 10 * 60             # a red row is checked again this often, until it answers
PROBES_PER_PASS = 2             # the most checks one drain pass makes
UNVERIFIED_FOR = 2 * RED_EVERY  # a mark only unknown checks follow is asked about after this
ENDING_DAYS = 2                 # a Claude login this close to its 30 days is amber
RED = (EXPIRED, MISSING)


@dataclass
class Login:
    """One row's identity and how it is checked; its state is read, never kept here."""
    id: str
    kind: str                      # claude, drive, key, adapter
    label: str
    where: str
    fix: str | None = None
    target: str = ""               # the config dir, the key's name, the adapter's space
    spaces: tuple = ()             # the spaces whose dir this is (claude)
    houses: bool = False           # a served space's houses run under it
    roles: list = field(default_factory=list)


# ----- which rows this machine has -----

def dir_name(config_dir: Path, spaces: list[str]) -> str:
    """A Claude dir's short name: `spaces/<name>/.claude` gives <name>; the default profile
    (`~/.claude`) takes its first space's."""
    path = Path(config_dir)
    if path.name == ".claude" and path.parent != Path.home() and path.parent.name:
        return path.parent.name
    return spaces[0] if spaces else "default"


def claude_specs(cfg) -> list[Login]:
    from keel import console, talker
    found: dict[str, dict] = {}

    def add(config_dir, space=None, role=None, houses=False):
        entry = found.setdefault(str(Path(config_dir)), {"spaces": [], "roles": [], "houses": False})
        if space and space not in entry["spaces"]:
            entry["spaces"].append(space)
        if role:
            entry["roles"].append(role)
        entry["houses"] = entry["houses"] or houses

    for name in cfg.served_spaces():
        add(cfg.spaces[name].config_dir, space=name, houses=True)
    if console.configured(cfg):
        add(console.config_dir(cfg), role="Bosun")
    paths = talker.paths_from(cfg)
    paths.home = cfg.home
    if talker.installed(paths):
        add(paths.config_dir, role="talker and voice")
    specs = []
    for text, entry in found.items():
        name = dir_name(Path(text), entry["spaces"])
        specs.append(Login(id=f"claude:{name}", kind="claude",
                           label="Claude " + ", ".join(entry["spaces"] + entry["roles"]),
                           where=text, fix=loginprobe.claude_fix(text), target=text,
                           spaces=tuple(entry["spaces"]), houses=entry["houses"]))
    return specs


def other_specs(cfg) -> list[Login]:
    from keel import service, voice
    specs = []
    store = cfg.backup_store or ""
    if store.startswith("rclone:") and cfg.backup_rclone_config and (cfg.backup_sets
                                                                      or cfg.backup_pull):
        specs.append(Login(id="drive", kind="drive", label="Drive (the backup store)",
                           where=str(cfg.backup_rclone_config), target=store,
                           fix=loginprobe.drive_fix(cfg.backup_rclone_config, store)))
    if service.installed(voice.LABEL, cfg.home):
        systemd = service.Manager(cfg.home).kind == service.SYSTEMD
        for name, row_id in KEY_ROWS.items():
            credential, keychain, label = voice.KEYS[name]
            where = (str(voice.credentials_dir(cfg.home) / credential) if systemd
                     else f"login keychain, {keychain}")
            specs.append(Login(id=row_id, kind="key", label=label, where=where, target=name,
                               fix=loginprobe.key_fix(name, cfg.root)))
    return specs


def adapter_specs(cfg) -> list[Login]:
    from keel import adapters
    return [Login(id=f"adapter:{name}", kind="adapter", label=f"{name} adapter",
                  where=str(cfg.spaces[name].adapter_dir), target=name)
            for name in cfg.served_spaces() if adapters.has_verb(cfg.spaces[name], "logins")]


def specs(cfg) -> list[Login]:
    return claude_specs(cfg) + other_specs(cfg) + adapter_specs(cfg)


# ----- the kept answers -----

def path_of(cfg) -> Path:
    return Path(cfg.state_dir) / FILE


def read(cfg) -> dict:
    try:
        found = json.loads(path_of(cfg).read_text())
    except (OSError, ValueError):
        return {"rows": {}}
    if not isinstance(found, dict) or not isinstance(found.get("rows"), dict):
        return {"rows": {}}
    return found


@contextlib.contextmanager
def changing(cfg):
    """The kept file, read and written back under one lock: the drain, the voice gateway,
    the talker and the backup's script all mark rows, and none may lose another's."""
    target = path_of(cfg)
    if not target.parent.is_dir():
        yield {"rows": {}}
        return
    with open(target.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = read(cfg)
        yield kept
        atomicfile.write_text(target, json.dumps(kept, indent=2, sort_keys=True) + "\n")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def instant(text) -> datetime | None:
    try:
        found = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def mark(cfg, row_id: str, why: str, ok: bool = False, at: datetime | None = None) -> None:
    """A failure seen (`ok` False): the row reads expired from now until it is checked. A
    success seen (`ok`): it counts as a good check at this instant."""
    at = at or now()
    with changing(cfg) as kept:
        entry = kept["rows"].setdefault(row_id, {})
        if ok:
            entry.update(state=GOOD, why="", at=iso(at))
            entry.pop("mark", None)
        else:
            entry["mark"] = {"why": str(why)[:200], "at": iso(at)}


def saw(cfg, config_dir, text: str | None, at: datetime | None = None) -> bool:
    """Mark the row of the Claude dir a turn ran under, when what it printed names a lost
    login. Never raises: every caller is already on a failure path of its own."""
    try:
        if not login.names_login(text):
            return False
        wanted = str(Path(config_dir).expanduser() if config_dir else Path.home() / ".claude")
        for spec in claude_specs(cfg):
            if spec.target == wanted:
                mark(cfg, spec.id, f"a turn said: {login.first_line(text)}", at=at)
                return True
    except Exception:  # noqa: BLE001 - a mark must never break the path that saw a failure
        return False
    return False


# The Logins row of each voice key, by its `keel voice key` name.
KEY_ROWS = {"google": "google-tts", "jev": "jev"}


class At:
    """Where a process with no config of its own keeps its answers: the voice gateway and
    the talker know their state dir (`harbor_voice.config.STATE`, `talker.Paths`) and never
    load a config, so a selftest that gives them a scratch home marks only the scratch."""

    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)


def saw_at(state_dir, config_dir, text: str | None) -> bool:
    """`saw` for a Claude dir that is not a space's (the talker's, the voice gateway's): its
    row id is the dir's name, as `claude_specs` gives it. Never raises."""
    if not login.names_login(text):
        return False
    return mark_at(state_dir, f"claude:{dir_name(Path(config_dir), [])}",
                   f"a turn said: {login.first_line(text)}")


def mark_at(state_dir, row_id: str, why: str, ok: bool = False) -> bool:
    """`mark` into `state_dir`'s Logins file. Never raises."""
    try:
        mark(At(state_dir), row_id, why, ok=ok)
        return True
    except Exception:  # noqa: BLE001 - the caller is already reporting a failure of its own
        return False


def unmark_at(state_dir, row_id: str) -> bool:
    """A success seen: the row's mark comes off, when it has one. Writes nothing when there
    is none. Never raises."""
    try:
        where = At(state_dir)
        if (read(where)["rows"].get(row_id) or {}).get("mark"):
            mark(where, row_id, "", ok=True)
        return True
    except Exception:  # noqa: BLE001 - the caller has just succeeded at its own work
        return False


# What a fetcher prints when a credential it holds was refused, besides the harness's own
# login words: Google's word for a bad key, OAuth's for a dead refresh token, OCI's for a
# refused signature, and a plain 401.
AUTH_WORDS = ("api key not valid", "api_key_invalid", "invalid_grant", "notauthenticated",
              "401 unauthorized", "http 401")


def names_auth(text: str | None) -> bool:
    lowered = (text or "").lower()
    return login.names_login(text) or any(words in lowered for words in AUTH_WORDS)


def saw_fetch(cfg, segment: Path, text: str) -> list[str]:
    """A failed fetch whose output names a refused credential marks the rows its segment
    declares in its `segment.md` frontmatter (`logins: google-tts`). Returns the rows
    marked; never raises."""
    try:
        if not names_auth(text):
            return []
        from keel import fetch
        fields, _body = fetch.parse_frontmatter((Path(segment) / "segment.md").read_text())
        rows = [one.strip() for one in fields.get("logins", "").split(",") if one.strip()]
        for row_id in rows:
            mark(cfg, row_id, f"the {Path(segment).name} fetch was refused: "
                              f"{login.first_line(text)}")
        return rows
    except Exception:  # noqa: BLE001 - a fetch failure is already being logged
        return []


# ----- one row's state -----

def newest(*answers: dict | None) -> dict | None:
    """The answer with the latest instant, among those that have one."""
    dated = [(instant(a.get("at")), a) for a in answers if isinstance(a, dict) and a.get("state")]
    dated = [(at, a) for at, a in dated if at is not None]
    return max(dated, key=lambda pair: pair[0])[1] if dated else None


def checked(cfg, spec: Login, kept: dict) -> dict | None:
    """The row's last check: a space dir's in `login.json` or ours, whichever is newer."""
    entry = kept["rows"].get(spec.id) or {}
    own = {k: entry[k] for k in ("state", "why", "at") if k in entry} or None
    spaced = [login.read(cfg).get(name) for name in spec.spaces]
    return newest(own, *spaced)


def settles(spec: Login, found: dict | None) -> bool:
    """A check that refutes or confirms a mark: good or red, never unknown, and never a key's
    good one, which only sees that the key is there."""
    state = (found or {}).get("state")
    return state in RED or (state == GOOD and spec.kind != "key")


def pending(spec: Login, marked: dict | None, last: dict | None, at: datetime) -> bool:
    """The mark stands: no check has settled it since it was made."""
    if not marked:
        return False
    if last is None or not settles(spec, last):
        return True
    return (instant(marked.get("at")) or at) > (instant(last["at"]) or at)


def overdue(marked: dict | None, last: dict | None, at: datetime) -> bool:
    """Only unknown answers have followed the mark for `UNVERIFIED_FOR`: a broken login and a
    flaky check look the same to him, so the ask comes anyway."""
    made = instant((marked or {}).get("at"))
    checked_at = instant((last or {}).get("at"))
    return (made is not None and checked_at is not None and checked_at >= made
            and (at - made).total_seconds() >= UNVERIFIED_FOR)


def state_of(cfg, spec: Login, kept: dict, at: datetime) -> dict:
    """`{state, why, at, expires, ending, marked, unverified}` for one row, from its last
    check, a newer mark, and (a Claude dir) the instant its login ends."""
    last = checked(cfg, spec, kept)
    found = {"state": UNKNOWN, "why": "not checked yet", "at": None} if last is None else {
        "state": last["state"], "why": last.get("why") or "", "at": last["at"]}
    was_red = found["state"] in RED
    marked = (kept["rows"].get(spec.id) or {}).get("mark")
    # A key's check only sees that the key is there, so a good one cannot refute the refusal
    # a mark recorded: only a real success clears it (`mark` with `ok`, from the gateway's
    # next 200 or `keel voice key set`). An unknown check settles no mark either (c-560).
    fresh = pending(spec, marked, last, at)
    newer = fresh and not (spec.kind == "key" and last is not None and last["state"] == GOOD)
    if fresh:
        found.update(state=EXPIRED, why=marked.get("why") or "a failure was seen", at=marked["at"])
    found["marked"] = fresh
    ends = loginprobe.forecast(spec.target) if spec.kind == "claude" else None
    found["expires"] = iso(ends) if ends else None
    found["ending"] = bool(ends and at < ends <= at + timedelta(days=ENDING_DAYS))
    if ends and ends <= at:
        was_red = True
        found.update(state=EXPIRED, why=f"its login ended {ends.date().isoformat()} "
                                        f"(30 days after the last /login)")
    found["unverified"] = newer and not was_red and not overdue(marked, last, at)
    return found


def adapter_rows(cfg, spec: Login, kept: dict) -> list[dict]:
    """The rows an adapter's last `logins check` returned, as rows of this list."""
    held = (kept.get("adapters") or {}).get(spec.target) or {}
    out = []
    for row in held.get("rows") or []:
        row_id = f"{spec.target}:{row['id']}"
        marked = (kept["rows"].get(row_id) or {}).get("mark")
        state = {"state": row["state"], "why": row.get("why") or "", "at": held.get("at")}
        newer = bool(marked) and ((instant(marked.get("at")) or now())
                                  > (instant(held.get("at")) or now()))
        if newer:
            state.update(state=EXPIRED, why=marked.get("why") or "", at=marked["at"])
        out.append(dict(state, id=row_id, kind="adapter", label=row.get("label") or row["id"],
                        where=row.get("where") or "", fix=row.get("fix"), houses=False,
                        expires=None, ending=False, marked=bool(marked),
                        unverified=newer and row["state"] not in RED))
    return out


def public(cfg, at: datetime | None = None, kept: dict | None = None) -> list[dict]:
    """Every row of this machine, as the deck and `keel logins` show it. The
    adapter's own unit is not a row: its rows are, plus one `unknown` row when its verb
    failed, so a broken verb is seen rather than silently leaving the list."""
    at = at or now()
    kept = kept if kept is not None else read(cfg)
    rows = []
    for spec in specs(cfg):
        if spec.kind == "adapter":
            listed = adapter_rows(cfg, spec, kept)
            unit = (kept.get("adapters") or {}).get(spec.target) or {}
            if unit.get("state") == UNKNOWN:
                listed.append({"id": spec.id, "kind": "adapter", "label": spec.label,
                               "where": spec.where, "fix": None, "houses": False,
                               "state": UNKNOWN, "why": unit.get("why") or "", "marked": False,
                               "unverified": False,
                               "at": unit.get("at"), "expires": None, "ending": False})
            rows += listed
            continue
        row = dict(state_of(cfg, spec, kept, at), id=spec.id, kind=spec.kind,
                   label=spec.label, where=spec.where, fix=spec.fix, houses=spec.houses)
        if spec.kind == "claude":
            # c-678: for the guided sign-in a red row draws (`K.signIn`, app/ui.signin.js)
            row.update(spaces=list(spec.spaces), stamp=login.signin_stamp(spec.target))
        rows.append(row)
    for row in rows:
        entry = kept["rows"].get(row["id"]) or {}
        row.update(host=cfg.host, good_at=entry.get("good_at"))
    return rows


def red(row: dict) -> bool:
    return row.get("state") in RED


# ----- the drain's pass -----

def due(cfg, spec: Login, kept: dict, at: datetime) -> tuple[int, bool]:
    """`(rank, due)`: marked first, then red, then never checked, then a day old. A mark is
    due until the list's own check has settled it, even one the hold's probe (which writes
    `login.json` too) has already refuted: only `keep` drops a mark, and a later unknown
    probe would otherwise be the newest check and revive it (c-560)."""
    if spec.kind == "adapter":
        unit = (kept.get("adapters") or {}).get(spec.target) or {}
        last = unit if unit.get("at") else None
        marks = [e.get("mark") for key, e in kept["rows"].items()
                 if key.startswith(spec.target + ":") and isinstance(e, dict)]
        is_red = unit.get("state") == UNKNOWN or any(
            row.get("state") in RED for row in unit.get("rows") or [])
    else:
        last = checked(cfg, spec, kept)
        marks = [(kept["rows"].get(spec.id) or {}).get("mark")]
        is_red = state_of(cfg, spec, kept, at)["state"] in RED
    last_at = instant((last or {}).get("at"))
    if last_at is None:
        return 2, True
    if any(m and (instant(m.get("at")) or at) > last_at for m in marks):
        return 0, True
    if spec.kind != "adapter" and marks[0] and settles(spec, last):
        return 0, True
    age = (at - last_at).total_seconds()
    if is_red:
        return 1, age >= RED_EVERY
    return 3, age >= DAY


def check(cfg, spec: Login) -> tuple[dict, list[dict] | None]:
    if spec.kind == "claude":
        return loginprobe.claude(spec.target), None
    if spec.kind == "drive":
        return loginprobe.drive(cfg.backup_rclone_config, spec.target), None
    if spec.kind == "key":
        from keel import service
        systemd = service.Manager(cfg.home).kind == service.SYSTEMD
        return loginprobe.key(spec.target, cfg.home, systemd), None
    return loginprobe.adapter(cfg.spaces[spec.target])


def keep(cfg, spec: Login, found: dict, rows: list[dict] | None, at: datetime) -> None:
    """Record one check: a space dir's in `login.json` too, so the drain's hold reads it."""
    entry = {"state": found["state"], "why": found.get("why", ""), "at": iso(at)}
    before = None if spec.kind == "adapter" else checked(cfg, spec, read(cfg))
    for name in spec.spaces:
        login.record(cfg, name, for_hold(found), at)
    with changing(cfg) as kept:
        if spec.kind == "adapter":
            kept.setdefault("adapters", {})[spec.target] = dict(entry, rows=rows or [])
            return
        row = kept["rows"].setdefault(spec.id, {})
        row.update(entry)
        settle(spec, row, before, found, at)


def settle(spec: Login, row: dict, before: dict | None, found: dict, at: datetime) -> None:
    """Drop the row's mark once a check has settled it, this one or the one it replaces (the
    hold's probe writes `login.json` too), so a later unknown answer cannot bring it back."""
    made = instant((row.get("mark") or {}).get("at"))
    if made is None:
        return
    settled = [instant(one["at"]) or at for one in (before, dict(found, at=iso(at)))
               if one and settles(spec, one)]
    if any(when >= made for when in settled):
        row.pop("mark", None)


def for_hold(found: dict) -> dict:
    """The answer as `login.json` keeps it: the hold and the doctor know good, expired and
    unknown, and a dir with no login at all is one whose houses cannot run, so `missing`
    is kept there as `expired` (c-560). The Logins list keeps the finer word."""
    return dict(found, state=EXPIRED) if found["state"] == MISSING else found


def remember(cfg, at: datetime) -> None:
    """When each row was last seen good, which is how the ask tells one red episode from
    the next (`keel/loginask.py`). Written only when a row's state changed."""
    kept = read(cfg)
    changes = {}
    for row in public(cfg, at, kept):
        entry = kept["rows"].get(row["id"]) or {}
        if entry.get("seen") != row["state"]:
            changes[row["id"]] = (row["state"], iso(at) if row["state"] == GOOD else None)
    if not changes:
        return
    with changing(cfg) as kept:
        for row_id, (state, good_at) in changes.items():
            entry = kept["rows"].setdefault(row_id, {})
            entry["seen"] = state
            if good_at:
                entry["good_at"] = good_at


def upkeep(cfg, at: datetime | None = None, limit: int = PROBES_PER_PASS) -> dict:
    """The drain's step: check the most due rows, then note what changed. Returns
    `{"checked": [ids], "red": n}` for the pass's log line."""
    at = at or now()
    kept = read(cfg)
    ranked = sorted(((due(cfg, spec, kept, at), spec) for spec in specs(cfg)),
                    key=lambda pair: pair[0][0])
    done = []
    for (_rank, is_due), spec in ranked:
        if not is_due or len(done) >= limit:
            continue
        found, rows = check(cfg, spec)
        keep(cfg, spec, found, rows, at)
        done.append(spec.id)
    remember(cfg, at)
    return {"checked": done, "red": sum(1 for row in public(cfg, at) if red(row))}


# ----- the verb: keel logins -----

def line(row: dict) -> str:
    state = row["state"].upper() if red(row) else row["state"]
    ends = f", ends {row['expires'][:10]}" if row.get("expires") else ""
    why = f": {row['why']}" if row.get("why") and row["state"] != GOOD else ""
    fix = f"\n    fix: {row['fix']}" if red(row) and row.get("fix") else ""
    return f"{row['id']:<18} {state}{why} ({row['where']}{ends}){fix}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel logins", description=(
        "Every credential this machine depends on: list them, check the due ones now, or "
        "mark one as failed or working."))
    parser.add_argument("--json", action="store_true", help="print the rows as JSON")
    subs = parser.add_subparsers(dest="verb")
    probe = subs.add_parser("check", help="check the due rows now (every row with --all)")
    probe.add_argument("--all", action="store_true")
    marking = subs.add_parser("mark", help="a failure or a success seen by a script")
    marking.add_argument("id")
    marking.add_argument("--why", default="")
    marking.add_argument("--ok", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    from keel import config as config_module
    args = build_parser().parse_args(argv)
    cfg = config_module.load()
    if args.verb == "mark":
        if not args.ok and not args.why.strip():
            print("keel logins mark: say what failed (--why) or that it works (--ok)",
                  file=sys.stderr)
            return 2
        mark(cfg, args.id, args.why, ok=args.ok)
    elif args.verb == "check":
        upkeep(cfg, limit=len(specs(cfg)) if args.all else PROBES_PER_PASS)
    rows = public(cfg)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print("\n".join(line(row) for row in rows) or "no logins on this machine")
    return 1 if any(red(row) for row in rows) else 0
