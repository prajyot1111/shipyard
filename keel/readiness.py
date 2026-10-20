"""What is set up here, and what is not (c-629, c-628 S1).

One answer, per space and for the install, to "is X set up, and if not, why, and which
first-run step fixes it". The deck receives it on `/api/state` as `readiness`; the pages
that depend on a capability (S3) and the first-run stepper (S4) read it, never their own
guess.

Each row is `{"ready": bool, "why": str, "step": str | None}`: `why` is one sentence a
person can read, `step` the first-run step id that sets it up (None when no step does). The
`login` row also carries `"sure": False` while the login could not be checked: it is ready,
since nothing should wait on it, and it is not confirmed (c-677).

- Per space (`space_rows`): `repos`, a repo of the space whose path holds `.git` (the
  install's own `packs` repo does not count, as for Setup's `fresh`); `tracker`,
  `codehost`, `reviews`, each ready when the space's pack declares it (`[capabilities]`,
  `keel/packs.py`) and every `[[requires]]` check that serves it passes; and `rules`
  (c-632), the space tier written and no longer its template.
- For the install (`install_rows`): `prerequisites` (the required rows of
  `keel/prereqs.py`), `login` (c-632, the install's Claude login as `keel/login.py` last
  found it), `voice` (the health row), `builder` (`builder.status`, and ready only when
  `console.start_refusal` would let Start run), `segments`,
  `phone` (c-632, whether `tailscale serve` proxies to the deck's port), and `browser`
  (c-678, whether Keel's own browser is in its folder; presence only), and `backup`
  (c-678, whether the config names a backup store).

The backend says the same sentence when it refuses a verb (c-631): `refusal(cfg, space,
cap)` is the repos row's `why`, or `undeclared`'s for a capability the space's pack does not
declare. Publish and Ship (`adapters.publish`), Reviews' and a card's adapter verbs
(`actions.act_adapter`), review upkeep and `kb create` with a repo ask it, so the deck's panel
and `kb` give one reason for one gap.

It reads and never writes or raises: a reading that fails is a row with `ready` false and
the error as its `why`. The slow readings (a pack's shell checks, the prerequisites,
`tailscale serve status`) are kept for `KEEP_SECONDS` per process; `fresh=True` reads again.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time

from keel import builder, health, login, packs, packsetup, prereqs, repolayout, terms
from keel.config import Config, Space
from keel.setupconfig import installed

KEEP_SECONDS = 300
RETRY_SECONDS = 30      # how long a read that could not answer is kept (`kept`, `retry_failed`)
CAPABILITIES = ("tracker", "codehost", "reviews", "ci")
# A capability a pack may leave out: its row is still shown, but the first run's Where
# finished work goes step counts it only for a space whose pack declares it (c-642 r2.F1),
# so the sandbox, which reads no builds, can finish. Review scanning too (c-730): a space
# that has not asked for it (`review_scan` off) is set up without it. And the tracker
# (c-730): a code host alone, as the GitHub pack is, is a whole connection.
OPTIONAL = ("tracker", "ci", "reviews")
# The words a row says for each capability. A ready tracker or code host is named by the
# pack's own `[terms]` (`tracker_name`, `codehost_name`, c-630) where it names one.
NOUNS = {"tracker": "tracker", "codehost": "code host", "reviews": "review scanning", "ci": "CI builds"}
NAMED = {"tracker": "tracker_name", "codehost": "codehost_name", "ci": "ci_name"}
# The first-run step that sets each row up (S4 builds the steps; here they are only ids).
STEPS = {"repos": "repos", "tracker": "integrations", "codehost": "integrations",
         "reviews": "integrations", "ci": "integrations", "rules": "rules", "prerequisites": "prerequisites",
         "login": "login", "voice": None, "builder": "builder", "segments": None,
         # c-678: the phone is set up from the last screen, More to set up later; voice has no
         # step (c-729, the owner's call): the page sends the user to Bosun for it
         "phone": "set-up", "browser": "browser", "backup": "backup"}
# `tailscale serve status` is asked with this timeout and kept like the other slow readings.
TAILSCALE_SECONDS = 5
# The install's login row while it does not work: a sign-in that ended, and one never made.
RAN_OUT = "Shipyard's Claude sign-in ran out, so no session can run"
# where another space has a sign-in of its own, only this space's sessions stopped (review F15)
RAN_OUT_SPACE = "Shipyard's Claude sign-in ran out, so no session of the {space} space can run"
NOT_SIGNED_IN = "Shipyard is not signed in to Claude yet"
LOCAL = r"(?:127\.0\.0\.1|localhost|\[::1\])"

_lock = threading.Lock()
_kept: dict = {}


def row(name: str, ready: bool, why: str) -> dict:
    return {"ready": bool(ready), "why": why, "step": STEPS[name]}


def kept(key, read, fresh: bool = False, retry_failed: bool = False):
    """`read()`, or its answer from the last `KEEP_SECONDS`. With `retry_failed`, a `read()`
    that returns None could not answer, and is kept for `RETRY_SECONDS` only: a failure that
    passes heals within that, and one that never passes costs one read per `RETRY_SECONDS`."""
    now = time.monotonic()
    with _lock:
        hit = _kept.get(key)
        if hit is not None and not fresh and now - hit[1] <= hit[2]:
            return hit[0]
    value = read()
    with _lock:
        _kept[key] = (value, now, RETRY_SECONDS if value is None and retry_failed else KEEP_SECONDS)
    return value


def forget() -> None:
    """Drop every kept reading (the suite, and a change that makes them stale), the loaded
    packs included, so Check again reads every pack afresh."""
    with _lock:
        _kept.clear()
    packs.forget()


# ----- per space -----

def repos_row(cfg: Config, space: Space) -> dict:
    home = installed(cfg)
    # The install's own repos (its packs and its memory) are not the user's (r1.F1).
    found = sorted(key for key, path in space.repos.items()
                   if (path / ".git").exists() and not builder.is_own(home, path))
    if found:
        return row("repos", True, f"{len(found)} repo{'' if len(found) == 1 else 's'}: "
                                  f"{', '.join(found)}")
    return row("repos", False, f"no repo is cloned for {space.name} yet")


def declared(space: Space):
    """`(pack, None)` for a space whose pack loads, else `(None, why)`: the sentence every
    capability of the space gets (no pack, a pack that does not load, an older adapter with
    no `pack.toml`)."""
    if space.adapter_dir is None:
        return None, f"no connection is turned on for {space.name}"
    try:
        pack = packs.at(space.adapter_dir)
    except packs.PackError as error:
        return None, f"the {space.adapter} connection does not load: {error}"
    if pack is None:
        return None, f"{space.adapter} is an adapter with no pack.toml, so it declares nothing"
    return pack, None


def wanted(space: Space) -> tuple[str, ...]:
    """The capabilities a space must have ready to be set up: every required one, and each
    optional one its pack declares."""
    return tuple(cap for cap in CAPABILITIES if cap not in OPTIONAL or undeclared(space, cap) is None)


def undeclared(space: Space, cap: str) -> str | None:
    """The sentence for a capability the space does not declare, or None when it does
    (c-631). The panel's row and the backend's refusal both say it. Review scanning is
    declared by the pack AND asked for by the space (`review_scan`, c-730): a space that
    turned it off files no review card, however able its pack is."""
    pack, why = declared(space)
    if why:
        return why
    if cap not in pack.capabilities:
        return f"the {pack.name} connection has no {NOUNS[cap]}"
    if cap == "reviews" and not getattr(space, "review_scan", True):
        return f"review scanning is off for {space.name}"
    return None


def refusal(cfg: Config, space: Space, cap: str) -> str | None:
    """Why a verb that needs `cap` is refused in `space`, or None when it may run (c-631).

    `repos` is the repos row's sentence while no repo is cloned. A capability is refused only
    when the space does not DECLARE it, never on a check that fails (decision
    `refusal-basis`): a failing check lets the verb run and fail in its own, more exact
    words, and a cached check could be stale. An older adapter with no `pack.toml` is not
    refused, since `adapters.routes_of` still serves it the legacy routes; its row says it
    declares nothing all the same."""
    if cap == "repos":
        found = repos_row(cfg, space)
        return None if found["ready"] else found["why"]
    if legacy(space):
        return None
    return undeclared(space, cap)


def legacy(space: Space) -> bool:
    """An adapter with no `pack.toml`: one that predates packs and declares nothing."""
    return space.adapter_dir is not None and not (space.adapter_dir / packs.PACK_FILE).is_file()


def pack_checks(cfg: Config, space: Space, pack: packs.Pack, fresh: bool = False) -> list[dict]:
    """The pack's `[[requires]]` checks for this space, kept: the capability rows and a pack's
    first-run steps (`keel/firstrun.py`) read the same run."""
    return kept(("checks", str(cfg.state_dir), space.name, pack.name),
                lambda: packs.checks(pack, packsetup.pack_env(cfg, pack)), fresh)


def capability_rows(cfg: Config, space: Space, fresh: bool = False) -> dict:
    """Each capability's row, and `declared` on it (c-730): whether the space may use it at
    all, which a row held up only by a failing check is, and an undeclared one is not (an
    older adapter, which `refusal` never refuses, is). The deck draws a page that needs a
    capability only while some space declares it (`rail: when-declared`, app/views.json)."""
    pack, why = declared(space)
    if why:
        return {name: dict(row(name, False, why), declared=legacy(space)) for name in CAPABILITIES}
    results = pack_checks(cfg, space, pack, fresh)
    out = {}
    for name in CAPABILITIES:
        missing = undeclared(space, name)
        if missing:
            out[name] = dict(row(name, False, missing), declared=False)
            continue
        failing = [check for check in results if name in check.get("for", []) and not check["ok"]]
        if failing:
            # `needs` (c-688): the failing checks as the pack returned them, each with its own
            # fix where the pack wrote one, so the row's stuck line can draw it
            out[name] = dict(row(name, False, "; ".join(f"{check['name']} is not set up: {check['why']}"
                                                        for check in failing)), needs=failing, declared=True)
        else:
            out[name] = dict(row(name, True, ready_why(pack, name)), declared=True)
    return out


def ready_why(pack: packs.Pack, name: str) -> str:
    """A ready capability's sentence: "<its name> is the tracker" where the pack names it,
    else that the pack provides it."""
    named = pack.terms.get(NAMED.get(name, ""))
    if named:
        return f"{terms.upper(named)} is the {NOUNS[name]}"
    return f"the {pack.name} connection provides its {NOUNS[name]}"


def rules_row(cfg: Config, space: Space) -> dict:
    """The space tier (`<install>/spaces/<space>/CLAUDE.md`) written, and no longer the
    template Setup starts it from (c-632)."""
    home = installed(cfg)
    if home is None:
        return row("rules", False, "only an install has space tiers")
    tier = repolayout.space_dir(home, space.name) / repolayout.TIER
    if not tier.is_file():
        return row("rules", False, f"the {space.name} space has no tier yet")
    # c-734 r1.F6: a tier still at the template it was copied from, the c-678 one included
    unwritten = {text.strip() for text in repolayout.unwritten(cfg.root, "space", space=space.name)}
    if tier.read_text().strip() in unwritten:
        return row("rules", False, f"the {space.name} tier is still the template")
    return row("rules", True, f"the {space.name} tier is written")


def space_rows(cfg: Config, space: Space, fresh: bool = False) -> dict:
    return {"repos": attempt("repos", lambda: repos_row(cfg, space)),
            **attempt_many(CAPABILITIES, lambda: capability_rows(cfg, space, fresh)),
            "rules": attempt("rules", lambda: rules_row(cfg, space))}


# ----- the install -----

def prerequisites_row(fresh: bool = False) -> dict:
    missing = prereqs.missing(kept(("prerequisites",), prereqs.gather, fresh))
    if missing:
        # each miss in the words the step's row and init use for it (`prereqs.miss_words`)
        return row("prerequisites", False, "; ".join(prereqs.miss_words(check) for check in missing))
    return row("prerequisites", True, "everything it needs is installed")


def login_space(cfg: Config) -> str | None:
    """The space whose login is the install's: personal, else the first."""
    return "personal" if "personal" in cfg.spaces else next(iter(cfg.spaces), None)


def login_row(cfg: Config) -> dict:
    """The install's Claude login as `keel/login.py` last found it, never probed here
    (c-632). `unknown` (a timeout, a network failure) is not read as a missing login, as
    the drain does not: houses try it as they run."""
    space = login_space(cfg)
    if space is None:
        return row("login", False, "there is no space to log in")
    entry = login.read(cfg).get(space) or {}
    state = entry.get("state")
    if state == login.GOOD:
        return row("login", True, "the install's Claude login works")
    if state == login.UNKNOWN:
        # ready, so nothing waits on it, and `sure` False: nobody may say it works (c-677)
        return dict(row("login", True, f"the install's Claude login could not be checked last time "
                                       f"({entry.get('why') or 'no reason'}); houses try it as they run"),
                    sure=False)
    # No command in either sentence (c-678): the Sign in to Claude step this row points at
    # shows the one command, and a second one here would not be the same line.
    if state == login.EXPIRED and login.ever_logged_in(cfg.spaces[space].config_dir) is not False:
        return row("login", False, RAN_OUT if login.sole(cfg, space) else RAN_OUT_SPACE.format(space=space))
    return row("login", False, NOT_SIGNED_IN)


def voice_row(cfg: Config) -> dict:
    found = next((item for item in health.current(cfg).get("services", [])
                  if item.get("name") == "voice"), None)
    if found is None or found.get("level") == health.OFF:
        return row("voice", False, "voice is not installed")
    if found.get("state") != "answering":
        return row("voice", False, f"voice is installed but {found.get('state') or 'unread'}")
    return row("voice", True, "voice is answering")


def builder_row(cfg: Config) -> dict:
    """Ready only when Bosun could start as the builder: the refusal Start gives (a config
    dir another Unix user owns, a bad `[builder] mode`, a clone it cannot make, a superuser)
    is the row's why. A
    clone Start makes first from a live checkout is not missing, and the why says so. The
    config dir's owner refuses every Start, so it is said with builder mode off too."""
    from keel import console         # noqa: PLC0415 - as doctor.builder_report: only this row needs it
    owned = console.other_owner(cfg) if console.configured(cfg) else None
    if owned:
        return row("builder", False, owned)
    found = builder.status(cfg)
    if found is None:
        return row("builder", False, "the builder is off")
    why = console.start_refusal(cfg, cloned_at_start=True)
    if why:
        return row("builder", False, why)
    label = found.get("label") or "the builder is on"
    coming = builder.to_clone(cfg)
    return row("builder", True, f"{label}; Start clones {', '.join(coming)}" if coming else label)


def segments_row(cfg: Config) -> dict:
    from keel import deckstate      # deckstate imports this module for /api/state
    found = deckstate.segments(cfg)
    if found:
        return row("segments", True, f"{len(found)} segment{'' if len(found) == 1 else 's'}")
    return row("segments", False, "no segment is installed")


def serve_status() -> dict:
    """`tailscale serve status --json`: `{"status": {...}}`, `{"missing": True}` where
    tailscale is not installed, or `{"error": why}`. Never raises, so a failure is kept too
    and a tailscale that hangs costs one timeout per `KEEP_SECONDS`, not one per state."""
    path = shutil.which("tailscale")
    if not path:
        return {"missing": True}
    try:
        done = subprocess.run([path, "serve", "status", "--json"], capture_output=True, text=True,
                              timeout=TAILSCALE_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        return {"error": f"tailscale serve status did not answer ({type(error).__name__})"}
    if done.returncode != 0:
        said = (done.stderr.strip().splitlines() or ["no reason given"])[-1]
        return {"error": f"tailscale serve status failed: {said}"}
    try:
        found = json.loads(done.stdout or "{}")
    except ValueError:
        return {"error": "tailscale serve status did not print JSON"}
    return {"status": found if isinstance(found, dict) else {}}


def proxied(status: dict, port: int) -> str | None:
    """The address (`https://<name>`) whose handler proxies to this machine's `port`, or None."""
    for site, web in (status.get("Web") or {}).items():
        for handler in ((web or {}).get("Handlers") or {}).values():
            target = str((handler or {}).get("Proxy") or "")
            if re.fullmatch(rf"https?://{LOCAL}:{int(port)}/?", target):
                host, _, at = str(site).rpartition(":")
                return f"https://{host}" if at == "443" else f"https://{site}"
    return None


def phone_row(cfg: Config, fresh: bool = False) -> dict:
    """Whether the phone reaches the deck: a `tailscale serve` handler proxies to the deck's
    `serve_port` (c-632). Read only; the first-run step shows the command to run."""
    port = cfg.serve_port
    if installed(cfg) is None:
        return row("phone", False, "the phone is set up for an install's deck")
    found = kept(("phone",), serve_status, fresh)
    if found.get("missing"):
        return row("phone", False, "tailscale is not installed")
    if found.get("error"):
        return row("phone", False, found["error"])
    address = proxied(found.get("status") or {}, port)
    if address is None:
        return row("phone", False, f"tailscale serve does not point at the deck (port {port})")
    return row("phone", True, f"the phone reaches the deck at {address}")


def browser_row() -> dict:
    """Whether Keel's own browser is in its folder (c-678, `keel/browserinstall.py`):
    presence only, nothing is launched. The first run's A browser for sessions step
    installs it; a card may take the browser only where it is used ([houses], Atlas 20)."""
    from keel import browserinstall     # noqa: PLC0415 - it reads prereqs, as the rows above do lazily
    there = browserinstall.presence()
    return row("browser", there, "Shipyard's browser is installed" if there else "Shipyard's browser is not installed")


def backup_row(cfg: Config) -> dict:
    """Whether backup is turned on (c-678): the config names a backup store. The row says
    that and no more (c-757 r1.F10): whether a copy has been written is the Back up step's
    to read (`keel/backupstatus.py`), and whether the copies are fresh is the tool's own
    alarm (`bin/keel-backup`), so this sentence claims nothing about copies."""
    store = getattr(cfg, "backup_store", None)
    return row("backup", bool(store), f"backup is on, into {store}" if store
               else "no backup is set up: the board lives only in this install")


def install_rows(cfg: Config, fresh: bool = False) -> dict:
    return {"prerequisites": attempt("prerequisites", lambda: prerequisites_row(fresh)),
            "login": attempt("login", lambda: login_row(cfg)),
            "voice": attempt("voice", lambda: voice_row(cfg)),
            "builder": attempt("builder", lambda: builder_row(cfg)),
            "segments": attempt("segments", lambda: segments_row(cfg)),
            "phone": attempt("phone", lambda: phone_row(cfg, fresh)),
            "browser": attempt("browser", browser_row),
            "backup": attempt("backup", lambda: backup_row(cfg))}


# ----- the whole -----

def build(cfg: Config, fresh: bool = False) -> dict:
    """`{"install": {...}, "spaces": {name: {...}}}`: what `/api/state` carries."""
    return {"install": install_rows(cfg, fresh),
            "spaces": {name: space_rows(cfg, space, fresh) for name, space in cfg.spaces.items()}}


def attempt(name: str, read) -> dict:
    """A row, or a not-ready row naming the error: readiness never takes the deck down."""
    try:
        return read()
    except Exception as error:  # noqa: BLE001 - a reading must never take the deck down
        return row(name, False, f"could not be read: {error}")


def attempt_many(names, read) -> dict:
    try:
        return read()
    except Exception as error:  # noqa: BLE001 - as `attempt`
        return {name: row(name, False, f"could not be read: {error}") for name in names}
