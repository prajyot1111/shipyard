"""Whether a space's login still works: the words that say it does not, and the probe that asks.

On 2026-09-24 the personal space's OAuth could not refresh. Every house turn ended at once
with "Login expired · Please run /login" and no Stop hook, the drain read the quiet houses as
the account's rate limit and spent its resumes on them, and `keel doctor` said "logged in"
because it only looked for a credential file on disk. Two facts were missing, and this
module is both:

- **The words** (`LOGIN_WORDS`, `names_login`). What Claude Code 2.1.281 prints when a
  space's login is gone, read out of the installed binary rather than guessed: its auth
  error strings, and the transcript record a house leaves (`"error":
  "authentication_failed"`, the text "Not logged in · Please run /login"). Two of its
  auth strings are deliberately NOT here: "Could not refresh your login because another
  Claude Code process is refreshing it ... Try again in a minute" and "Authentication
  error · This may be a temporary network issue". Both are transient, and a transient
  failure read as an expired login would block houses that would have carried on.
- **The probe** (`probe`, `check`). One real call under the space's config dir, `claude -p
  --no-session-persistence --model haiku` with a one-word prompt and a short timeout, in
  the space's own environment without his token (`harness.login_probe`). It answers
  `good` (exit 0), `expired` (the words above anywhere in what it printed) or `unknown`
  (a timeout, a network failure, a rate limit, anything else), and `unknown` is never
  reported as expired. Recorded 2026-09-24 under a config dir with no login: stdout
  "Not logged in · Please run /login", exit 1, under a second.

The answer is kept per space in `state/login.json` with the instant it was taken, and
`check` asks again only when that is older than `PROBE_EVERY`, so the drain can ask on
every pass and still probe a space at most once in ten minutes. It is a reading of the
machine, like the drain log, not board state: it is never the reason a card moves, only
what the drain consults before it spends a resume or starts a house. `keel doctor` probes
whatever the file says (`force`), because he asked.
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from keel import harness

GOOD, EXPIRED, UNKNOWN = "good", "expired", "unknown"
FILE = "login.json"
CREDENTIALS = ".credentials.json"
PROBE_EVERY = 10 * 60          # seconds between two probes of one space on the drain's own
PROBE_TIMEOUT = 45             # a one-word haiku turn answers in a few seconds
# What Claude Code 2.1.281 prints for a login that is gone, matched without regard to case.
# "login expired" covers "Login expired · Please run /login", "Login expired · Run /login
# to sign in again, ..." and "Anthropic profile login expired · Re-authenticate ...".
LOGIN_WORDS = (
    "login expired",
    "please run /login",
    "run /login to sign in again",
    "not logged in",
    "oauth token revoked",
    "oauth token has expired",
    "invalid api key",
    "authentication required · sign in again",
    # 2026-09-27, a connected voice turn: "Failed to authenticate: OAuth session expired and
    # could not be refreshed". Unlike the refresh another process is holding, it does not
    # pass on its own (c-558).
    "oauth session expired",
)


def names_login(text: str | None) -> bool:
    """The text says the login is gone, in one of the harness's own phrasings."""
    lowered = (text or "").lower()
    return any(words in lowered for words in LOGIN_WORDS)


# ----- what he is told to do -----

def fix_command(config_dir) -> str:
    """How he logs the space back in. The default profile is reached with the variable
    UNSET (`harness.is_default_config_dir` says why), so it is named only for the others."""
    if harness.is_default_config_dir(config_dir):
        return "run claude, then /login"
    return f"run CLAUDE_CONFIG_DIR={config_dir} claude, then /login"


def gone(space: str, config_dir) -> str:
    """`the <space> login expired`, or, for a dir known never to have held a login, `the
    <space> space is not logged in` (c-560). The hold's reason and the drain's log say it."""
    if ever_logged_in(config_dir) is False:
        return f"the {space} space is not logged in"
    return f"the {space} login expired"


def block_reason(space: str, config_dir) -> str:
    """The one plain reason a house blocked for its login carries: a dir that never held a
    login is not called expired (c-560)."""
    return (f"{gone(space, config_dir)}, so its houses cannot run: {fix_command(config_dir)}; "
            f"they resume on their own once it works")


# ----- the probe -----

def classify(result: subprocess.CompletedProcess) -> dict:
    """`{state, why}` from a finished probe: the words win over the exit code, because the
    harness prints them on stdout with exit 1 and a future version might exit 0."""
    said = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
    if names_login(said):
        return {"state": EXPIRED, "why": first_line(said)}
    if result.returncode == 0:
        return {"state": GOOD, "why": ""}
    return {"state": UNKNOWN, "why": f"exit {result.returncode}: {first_line(said) or 'no output'}"}


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def probe(config_dir) -> dict:
    """One real call under `config_dir`; `{state, why}`, never raising."""
    try:
        with tempfile.TemporaryDirectory(prefix="keel-login-") as scratch:
            result = harness.login_probe(config_dir, cwd=scratch, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"state": UNKNOWN, "why": f"no answer in {PROBE_TIMEOUT}s"}
    except (OSError, subprocess.SubprocessError, harness.HarnessError) as error:
        return {"state": UNKNOWN, "why": f"{type(error).__name__}: {error}"}
    return classify(result)


# ----- the kept answers -----

def path_of(cfg) -> Path:
    return Path(cfg.state_dir) / FILE


def read(cfg) -> dict:
    """`{space: {state, why, at}}` as last recorded here; {} when there is none."""
    try:
        found = json.loads(path_of(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def record(cfg, space: str, found: dict, at: datetime) -> dict:
    """Keep one space's answer with its instant, written whole so a reader never sees half.
    A state dir that is not there is not made: `keel doctor` checks it and creates nothing,
    so its answer is then said and not kept."""
    entry = {"state": found["state"], "why": found.get("why", ""),
             "at": at.isoformat(timespec="seconds")}
    target = path_of(cfg)
    if not target.parent.is_dir():
        return entry
    kept = dict(read(cfg), **{space: entry})
    scratch = target.with_suffix(".json.tmp")
    scratch.write_text(json.dumps(kept, indent=2) + "\n")
    os.replace(scratch, target)
    return entry


def age_seconds(entry: dict | None, at: datetime) -> float | None:
    try:
        return (at - datetime.fromisoformat(entry["at"])).total_seconds()
    except (TypeError, KeyError, ValueError):
        return None


def now() -> datetime:
    return datetime.now().astimezone()


def check(cfg, space: str, at: datetime | None = None, force: bool = False) -> dict:
    """The space's login: the kept answer while it is under `PROBE_EVERY` old, else a probe
    now (always a probe with `force`). Returns the kept entry {state, why, at}."""
    at = at or now()
    entry = read(cfg).get(space)
    age = age_seconds(entry, at)
    if not force and age is not None and 0 <= age < PROBE_EVERY:
        return entry
    return record(cfg, space, probe(cfg.spaces[space].config_dir), at)


def state_of(cfg, space: str) -> str | None:
    """What the kept answer says, without probing: good, expired, unknown or None."""
    return (read(cfg).get(space) or {}).get("state")


def is_expired(cfg, space: str) -> bool:
    return state_of(cfg, space) == EXPIRED


def stamp(entry: dict) -> str:
    """`HH:MM`, local, of the instant the answer was taken."""
    try:
        return datetime.fromisoformat(entry["at"]).astimezone().strftime("%H:%M")
    except (TypeError, KeyError, ValueError):
        return "?"


def ever_logged_in(config_dir) -> bool | None:
    """Whether this config dir has ever held a login: a credentials file (Linux), or the
    account Claude Code records in its `.claude.json` beside a keychain login (macOS; the
    default profile's is `~/.claude.json`), so a fresh install's never has. Only the key's
    presence is read. None when the file is there but cannot be read or parsed: Claude Code
    rewrites it often, and one caught mid-write says nothing, so every caller then falls
    back to calling the login expired."""
    path = Path(config_dir).expanduser()
    if (path / CREDENTIALS).is_file():
        return True
    state = (Path.home() / ".claude.json" if harness.is_default_config_dir(config_dir)
             else path / ".claude.json")
    try:
        data = json.loads(state.read_text())
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return bool(data.get("oauthAccount"))


def said(entry: dict | None, config_dir) -> str:
    """The doctor's words for one space: `logged in (probed HH:MM)`, `LOGIN EXPIRED (probed
    HH:MM): run ...`, or `login unknown (probed HH:MM: why)`."""
    if not entry:
        return "login not probed"
    if entry["state"] == GOOD:
        return f"logged in (probed {stamp(entry)})"
    if entry["state"] == EXPIRED:
        word = "NOT LOGGED IN" if ever_logged_in(config_dir) is False else "LOGIN EXPIRED"
        return f"{word} (probed {stamp(entry)}): {fix_command(config_dir)}"
    return f"login unknown (probed {stamp(entry)}: {entry.get('why') or 'no reason'})"


def public(cfg, space: str) -> dict | None:
    """What the deck shows for one space: the kept answer plus the fix and whether the dir
    never held a login (`never_logged_in`, so the banner does not call it expired), or None.
    The dir is looked at only when the answer is expired, the one state that wording is for.
    `signin` is the one command the guided sign-in shows (c-678, `signin_command`), and `stamp`
    when the sign-in file last changed (`signin_stamp`), which its block watches. `only` is
    whether every space signs in there (`sole`): the banner says "no session can run" only
    then, and names the space otherwise (review F15)."""
    entry = read(cfg).get(space)
    if not entry or space not in cfg.spaces:
        return None
    config_dir = cfg.spaces[space].config_dir
    never = entry.get("state") == EXPIRED and ever_logged_in(config_dir) is False
    return dict(entry, fix=fix_command(config_dir), never_logged_in=never,
                signin=signin_command(config_dir), stamp=signin_stamp(config_dir), only=sole(cfg, space))


def sole(cfg, space: str) -> bool:
    """Whether every space of the config signs in with `space`'s folder."""
    mine = Path(cfg.spaces[space].config_dir).expanduser()
    return all(Path(other.config_dir).expanduser() == mine for other in cfg.spaces.values())


def signin_file(config_dir) -> Path | None:
    """The file a sign-in under `config_dir` leaves, where one is there now: the credentials
    file (Linux), else the account file once it names an account (macOS, `ever_logged_in`)."""
    path = Path(config_dir).expanduser()
    if (path / CREDENTIALS).is_file():
        return path / CREDENTIALS
    if ever_logged_in(config_dir) is not True:
        return None
    return Path.home() / ".claude.json" if harness.is_default_config_dir(config_dir) else path / ".claude.json"


def signin_stamp(config_dir) -> int | None:
    """When the sign-in file last changed (whole seconds), or None with no sign-in there
    (c-678). The guided sign-in watches this: a stamp that is new while the login is not
    known good is a sign-in just made, and the page asks for the one probe."""
    found = signin_file(config_dir)
    try:
        return int(found.stat().st_mtime) if found is not None else None
    except OSError:
        return None


def signin_command(config_dir) -> str:
    """The line the guided sign-in asks the user to paste into a terminal (c-678): `claude
    auth login` under the space's own config dir, the same one the Logins list copies
    (`loginprobe.claude_fix`), so the page, the banner and that list name one command."""
    from keel import loginprobe         # noqa: PLC0415 - loginprobe imports this module
    return loginprobe.claude_fix(config_dir)
