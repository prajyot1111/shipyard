"""The cheap checks behind the Logins list (`keel/logins.py`), one per kind of credential,
and the one-liner that logs each back in.

Every check answers `{state, why}` with the state one of `good`, `expired`, `missing`,
`unknown` or (a voice key) `unset`, never raises, and never prints, keeps or returns a
secret:

- **A Claude config dir** (`claude`): the space probe `login.probe` (one word on haiku,
  which costs nothing when the login is gone), plus `forecast`, which reads only the
  `refreshTokenExpiresAt` instant out of `.credentials.json`. Measured on the box on
  2026-09-27: that instant is the `/login` plus exactly 30 days, and an access token
  refreshing does not move it, so a dir whose instant has passed is expired whatever a
  cached token still says. On macOS the login lives in the keychain and there is no file,
  so there is no forecast there, only the probe.
- **Drive** (`drive`): `rclone lsd <remote>:` with the backup's own config, the same check
  `bin/keel-backup-setup` makes. rclone refreshes the token as it goes; a dead refresh token
  answers with the words `bin/keel-backup`'s `rcl` already recognises.
- **A voice key** (`key`): set or `unset`, the way `keel voice key check` asks (the file's
  size on Linux, the keychain item's attributes on macOS, never `-w`; only `security`'s
  exit 44, item not found, is `unset`, any other failure `unknown`). Whether it is VALID
  comes from the gateway's own 401 or 403 (decision D2): Keel never reads either key.
- **An adapter's rows** (`adapter`): its optional `logins check` verb, which prints
  `{"logins": [{id, label, state, why, fix, where}]}` and nothing secret.
"""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from keel import adapters, harness, login

GOOD, EXPIRED, MISSING, UNKNOWN = "good", "expired", "missing", "unknown"
# A voice key that was never set: both are optional (the gateway runs on without either, and
# install leaves an empty file for each on purpose), so this is not red (c-560).
UNSET = "unset"
STATES = (GOOD, EXPIRED, MISSING, UNKNOWN, UNSET)
# `security`'s exit for an item that is not there (errSecItemNotFound); any other failure,
# a locked keychain or a denied read, says nothing about whether the key is set (c-560).
KEYCHAIN_NOT_FOUND = 44
TIMEOUT = 20                   # rclone, oci and the adapter; the Claude probe keeps its own 45
CREDENTIALS = login.CREDENTIALS
# What rclone says for a refresh token that has died (bin/keel-backup's `rcl` reads the same).
RCLONE_AUTH = re.compile(r"invalid_grant|cannot fetch token|couldn.t fetch token|"
                         r"unauthorized_client|invalid_client|token (has been )?(expired|revoked)|"
                         r"401 Unauthorized", re.IGNORECASE)
# What the OCI CLI prints for a signature it refused: a ServiceError whose JSON spans lines.

def answer(state: str, why: str = "") -> dict:
    return {"state": state, "why": why[:200]}


def said(done: subprocess.CompletedProcess) -> str:
    return f"{done.stdout or ''}\n{done.stderr or ''}".strip()


def run(argv: list[str], timeout: int = TIMEOUT) -> subprocess.CompletedProcess | dict:
    """The command's result, or an `unknown` answer when it could not run."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return answer(UNKNOWN, f"no answer in {timeout}s")
    except OSError as error:
        return answer(UNKNOWN, f"{type(error).__name__}: {error}")


# ----- a Claude config dir -----

def claude(config_dir) -> dict:
    """The space probe, the very check the drain's hold and its release make
    (`login.check`), so the list never holds a dir the release then finds working (c-560).
    An expired answer from a dir that never held a login (`login.ever_logged_in`) is
    `missing`. Under no login the probe answers locally, in under a second, with no turn."""
    found = login.probe(config_dir)
    if found["state"] == EXPIRED and login.ever_logged_in(config_dir) is False:
        return answer(MISSING, f"no login in {config_dir}")
    return answer(found["state"], found.get("why", ""))


def forecast(config_dir) -> datetime | None:
    """When the dir's refresh token ends, from its credentials file; None when there is no
    file (macOS keeps it in the keychain) or no such field. Only the instant is read out."""
    try:
        data = json.loads((Path(config_dir) / CREDENTIALS).read_text())
        stamp = data["claudeAiOauth"]["refreshTokenExpiresAt"]
        return datetime.fromtimestamp(float(stamp) / 1000, timezone.utc)
    except (OSError, ValueError, TypeError, KeyError):
        return None


# ----- Drive -----

def drive(rclone_config, store: str) -> dict:
    remote = store.split(":")[1] if store.count(":") >= 2 else ""
    if not remote:
        return answer(UNKNOWN, f"the store {store!r} is not rclone:<remote>:<path>")
    if not Path(rclone_config).is_file():
        return answer(MISSING, f"no {rclone_config}")
    binary = shutil.which("rclone")
    if binary is None:
        return answer(UNKNOWN, "rclone is not installed here")
    done = run([binary, "--config", str(rclone_config), "--retries", "1",
                "--low-level-retries", "2", "lsd", f"{remote}:"])
    if isinstance(done, dict):
        return done
    text = said(done)
    if RCLONE_AUTH.search(text):
        return answer(EXPIRED, login.first_line(RCLONE_AUTH.search(text).group(0)
                                                + ": " + login.first_line(text)))
    if done.returncode == 0:
        return answer(GOOD)
    return answer(UNKNOWN, f"exit {done.returncode}: {login.first_line(text) or 'no output'}")


# ----- a voice key -----

def key(name: str, home: Path, systemd: bool) -> dict:
    from keel import voice
    credential, keychain, label = voice.KEYS[name]
    if systemd:
        source = voice.credentials_dir(home) / credential
        try:
            size = source.stat().st_size
        except OSError:
            return answer(UNSET, f"no {source}")
        return answer(GOOD) if size else answer(UNSET, f"{source} is empty")
    done = run(["security", "find-generic-password", "-s", keychain])
    if isinstance(done, dict):
        return done
    if done.returncode == 0:
        return answer(GOOD)
    if done.returncode == KEYCHAIN_NOT_FOUND:
        return answer(UNSET, f"no {label} in the keychain")
    return answer(UNKNOWN, f"exit {done.returncode}: {login.first_line(said(done)) or 'no output'}")


# ----- an adapter's rows -----

def adapter(space) -> tuple[dict, list[dict]]:
    """`({state, why}, rows)`: the verb's own answer, and its rows cleaned to the fields the
    list carries. A verb that failed is one `unknown` answer and no rows."""
    try:
        data = json.loads(adapters.run(space, "logins", "check", timeout=TIMEOUT * 3) or "{}")
    except (adapters.AdapterError, ValueError) as error:
        return answer(UNKNOWN, str(error)), []
    rows = []
    for row in (data.get("logins") if isinstance(data, dict) else None) or []:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip():
            continue
        state = row.get("state") if row.get("state") in STATES else UNKNOWN
        rows.append({"id": str(row["id"]).strip(), "label": str(row.get("label") or row["id"]),
                     "state": state, "why": str(row.get("why") or "")[:200],
                     "fix": str(row.get("fix") or "") or None,
                     "where": str(row.get("where") or "")})
    return answer(GOOD), rows


# ----- the one-liners -----

def claude_fix(config_dir) -> str:
    """`claude auth login` under the dir; the default profile is reached with the variable
    unset (`harness.is_default_config_dir`), so it names none."""
    binary = shutil.which("claude") or "claude"
    command = (f"{binary} auth login" if harness.is_default_config_dir(config_dir)
               else f"CLAUDE_CONFIG_DIR={config_dir} {binary} auth login")
    return command


def drive_fix(rclone_config, store: str) -> str:
    """rclone mints a token where a browser is, which is this machine."""
    remote = store.split(":")[1] if store.count(":") >= 2 else "keel-drive"
    return f"rclone --config {rclone_config} config reconnect {remote}:"


def key_fix(name: str, root) -> str:
    flag = "" if name == "google" else f" --name {name}"
    return f"cd {root} && bin/keel voice key set{flag}"
