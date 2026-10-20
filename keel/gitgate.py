"""The git gate: the one way Bosun's own Unix user writes to Keel's repo (docs/atlas/96-bosun.md,
"Bosun's own user").

Bosun runs as the `bosun` user on the box, in its own clone, and cannot open anything of the
user Keel runs as. It reaches Keel's repo over ssh to that user with a key whose
`authorized_keys` line forces `bin/keel-git-gate`:

- **The gate** (`gate_argv`) runs only `git-upload-pack` or `git-receive-pack`, and only on
  the checkout the gate itself lives in, with `KEEL_GIT_GATE=bosun` in the environment. Any
  other command, a shell included, is refused.
- **The receive hook** (`bin/keel-git-receive`, installed as the repo's `pre-receive`)
  checks only a push that came through the gate (`refusals`): `refs/heads/next` as a
  fast-forward, never deleted, and branches under `refs/heads/bosun/`; every other ref,
  `main` above all, is refused. `main` moves only on his deploy, which needs his token,
  and the token is in a directory Bosun's user cannot enter.

A push from anywhere else (the Mac, a landing) does not carry the variable and is not this
hook's to judge.
"""

import os
import shlex
from pathlib import Path

GATE_ENV = "KEEL_GIT_GATE"
BOSUN = "bosun"
PACKS = ("git-upload-pack", "git-receive-pack")
INTEGRATION_REF = "refs/heads/next"
OWN_PREFIX = "refs/heads/bosun/"
ZERO = "0" * 40


class GateRefused(Exception):
    """What the gate or the hook says to the pusher, one line."""


def gate_argv(original: str | None, root: Path) -> list[str]:
    """The argv the gate runs for `SSH_ORIGINAL_COMMAND`, or GateRefused."""
    try:
        words = shlex.split(original or "")
    except ValueError:
        words = []
    if len(words) != 2 or words[0] not in PACKS:
        raise GateRefused("this key runs git fetch and push on Keel's repo, nothing else")
    asked = Path(words[1].replace("~", str(Path.home()), 1)).expanduser()
    if not asked.is_absolute():
        asked = Path.home() / asked
    if asked.resolve() not in (root.resolve(), (root / ".git").resolve()):
        raise GateRefused(f"this key reaches {root} only, not {words[1]}")
    return [words[0], str(root)]


def gate_env() -> dict:
    return dict(os.environ, **{GATE_ENV: BOSUN})


def refusals(lines: list[str], is_ancestor) -> list[str]:
    """Why each ref update in a gated push is refused (empty: the push goes through).
    `is_ancestor(old, new)` answers whether `new` fast-forwards `old`."""
    said = []
    for line in lines:
        parts = line.split()
        if len(parts) != 3:
            continue
        old, new, ref = parts
        if ref.startswith(OWN_PREFIX):
            continue
        if ref != INTEGRATION_REF:
            said.append(f"{ref}: Bosun pushes {INTEGRATION_REF} and {OWN_PREFIX}* only; "
                        f"main moves on the user's deploy")
        elif new == ZERO:
            said.append(f"{ref}: the integration branch is never deleted")
        elif old != ZERO and not is_ancestor(old, new):
            said.append(f"{ref}: only a fast-forward; merge {INTEGRATION_REF} into your batch "
                        f"and push again")
    return said


def gated() -> bool:
    return os.environ.get(GATE_ENV) == BOSUN
