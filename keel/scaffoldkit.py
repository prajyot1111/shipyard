"""`keel new pack <name> --kit` (c-735): a pack that starts on the pack kit.

Where a plain `keel new pack` copies the sandbox, this writes a code host pack whose every
verb is a shim over the kit (`keel/packkit/verbs.py`), so what is left to write is only what
is about the host: its layer (`<stem>_layer.py`, every operation a stub that says it is not
written yet), its requirement checks (`<stem>_ready.py`), its guard policy
(`<stem>_fence.py`), its rules, and its stand-in hook (`tests/standin.py`), which serves the
conformance suite's world as the host would. The stem is the name with `-` as `_`, so a
hyphenated name makes modules Python can import (r2.F3). `tests/test_conformance.py` subclasses the
three contracts a code host with no review requests holds (`ReviewsContract` is for one that
claims `reviews`), so `keel pack check <dir>` fails until the layer is written and passes
when it is: that is when a draft is done (`keel/packdraft.py`, the first run's draft choice). The scaffold loads
what it wrote (`packs.load`) and removes it again when that fails, as `keel/scaffold.py`
does for every kind.
"""

import json
from pathlib import Path

from keel import terms

TERMS = ("change", "changes", "change_short", "changes_short")
VERBS = ("worktree", "brief", "pr", "publishable", "publish", "ship", "act", "logins", "ready")

PACK_TOML = '''# The {name} pack, made by `keel new pack {name} --kit` (c-735): a code host on the pack kit.
# Every verb is a shim over the kit; write the host layer ({stem}_layer.py), its requirement
# checks ({stem}_ready.py), its guard policy ({stem}_fence.py) and its stand-in hook
# (tests/standin.py), then run `keel pack check <this folder>` until it passes.
# docs/atlas/62-packs.md, "The pack kit", is the contract.
name = "{name}"
version = "1"
description = "The {name} pack: say here which code host it connects and what it does there."

[provides]
rules = ["rules/house.md", "rules/comments.md"]
skills = []

[capabilities]
codehost = true

[guard]
tools = ["git"]

# What the host calls a change: the engine's own words until you say the host's
[terms]
change = "{change}"
changes = "{changes}"
change_short = "{change_short}"
changes_short = "{changes_short}"
codehost_name = "{title}"

[[requires]]
name = "git"
kind = "command"
check = "./ready git"
for = ["codehost"]
why = "git clones and pushes each repo, so it has to be installed."
fix = "Install git, then check again. Shipyard never installs it for you."
done_when = "`git --version` prints a version."
'''

SHIM = '''#!/usr/bin/env python3
"""`{verb}`: the kit's verb for this pack (keel/packkit/verbs.py)."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), os.environ.get("KEEL_HOME") or str(HERE.parent.parent), str(HERE.parent.parent)]

from keel.packkit import verbs  # noqa: E402

sys.exit(verbs.run("{verb}", sys.argv[1:], pack=HERE, layer="{stem}_layer"))
'''

GUARD = '''#!/usr/bin/env python3
"""`guard <id>`: whether a command this card's house is about to run may run ({stem}_fence.py,
keel/packkit/guard.py)."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), os.environ.get("KEEL_HOME") or str(HERE.parent.parent), str(HERE.parent.parent)]

import {stem}_fence  # noqa: E402
from keel.packkit import guard  # noqa: E402

sys.exit(guard.main(sys.argv[1:], pack=HERE, policy={stem}_fence.POLICY))
'''

LAYER = '''"""The {name} pack's host layer (keel/packkit/layer.py is the contract).

Every operation below is a stub: write each one against your host, through one of the kit's
transports (keel/packkit/cli.py for a command line tool, keel/packkit/rest.py for an HTTP
API) or your own, raising only the kit's errors. `HOST` says what the host is called and how
its addresses read; `address` asks nothing of the host.
"""

from urllib.parse import urlsplit

from keel.packkit import VERSION
from keel.packkit.errors import HostError
from keel.packkit.layer import HostConfig, Repo

KIT = VERSION


def address(remote_url: str, clone=None) -> Repo | None:
    """The repository an http(s) address names: its last two parts, `owner/repo`."""
    parts = urlsplit((remote_url or "").strip())
    names = [part for part in parts.path.removesuffix(".git").split("/") if part]
    if parts.scheme not in ("http", "https") or not parts.hostname or len(names) < 2:
        return None
    base = f"{{parts.scheme}}://{{parts.netloc.rsplit('@', 1)[-1]}}" + "".join(f"/{{one}}" for one in names[:-2])
    return Repo("/".join(names[-2:]), base, clone)


def pr_url(repo, number: int) -> str:
    return f"{{repo.base}}/{{repo}}/pulls/{{int(number)}}"


HOST = HostConfig(name="{title}", on="on {title}", address=address, pr_url=pr_url, ready="{stem}_ready",
                  guard="{stem}_fence")


def unwritten(operation: str):
    def stub(*args, **kwargs):
        raise HostError(f"{{operation}} is not written yet: write it in {stem}_layer.py against your host")
    stub.__name__ = operation
    return stub


for _operation in ("find_open", "get", "open_pr", "set_ready", "set_body", "said", "checks", "comment", "reply",
                   "post_review", "review_requests", "mine", "default_branch", "protected", "account",
                   "signed_in", "access"):
    globals()[_operation] = unwritten(_operation)
'''

READY = '''"""What the {name} pack needs on the machine (`ready`, `logins check`): each a row with a
reason and a fix (keel/packkit/ready.py). Add the sign-in, the address and the access checks
your host needs, each with its `[[requires]]` in pack.toml."""

import shutil

from keel.packkit import ready as kit

NAMES = ("git",)


def installed() -> dict:
    if shutil.which("git"):
        return kit.row("git", True, "git is installed.")
    return kit.row("git", False, "git is not installed.", "Install git, then check again.")


CHECKS = {{"git": installed}}


def rows() -> list[dict]:
    return [CHECKS[name]() for name in NAMES]


def login_rows() -> list[dict]:
    return []
'''

FENCE = '''"""The {name} pack's guard policy (keel/packkit/guard.py judges with it): the host tools it
reads besides git, and its sentences. Add a judge for any tool a house could write to the
host with."""

from keel.packkit.guard import GuardPolicy

UNREAD = ("this command could not be read (a quote that never closes, or a nesting too deep) and it names "
          "a push or this pack's own verbs, so it is refused: write it as one plain command.")
SIGN_IN = "the sign-in is not yours to read or change: `{{said}}` is refused."
POLICY = GuardPolicy(tools={{}}, unread=UNREAD, sign_in=SIGN_IN)
'''

HOUSE = '''## Your house: a repo on {title}

You work in `{{worktree}}` on branch `{{branch}}`, cut from `{{remote}}/{{base}}`.{{siblings}} This branch
is yours: commit on it, and it is the only branch you ever push. Opening a {{change}} is this
pack's `pr <id> --draft`; marking it ready is Approve outcome's; replies are posted by Ship
from the verdicts you record; merging is done on {title} by a person. Keel reads each command
before it runs and refuses the ones that are not yours. It is a fence, not a wall.
'''

COMMENTS = '''## How to judge review on your {title} change

Judge each item Keel sends: fix only what is valid, with commits on your branch, and record
one `kb verdict <card> <handle>` per item. Ship pushes your commits and posts the replies kept.
'''

SUITEFENCE = '''"""The suite fence for this pack's suite (tests/fence.py says what it does and why), and
the kit bound to this pack, as each verb's shim binds it."""

import os
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(PACK), os.environ.get("KEEL_HOME") or str(PACK.parent.parent), str(PACK.parent.parent)]

from keel.packkit import pack  # noqa: E402
from tests import fence  # noqa: E402

fence.install()
pack.bind(PACK, "{stem}_layer")
'''

STANDIN = '''"""The {name} pack's stand-in hook: how the conformance suite's world (keel/packkit/world.py)
reaches this pack's real layer, as its host would. Serve it the way the layer talks to the
host (a command line tool on PATH, or an HTTP API on 127.0.0.1), and say the address a clone
of a world repository has. keel/packkit/standin.py is the reference: the contract over a world."""

from keel.packkit.world import World


class StandIn:
    """Mixed into each conformance subclass (tests/test_conformance.py)."""

    def host_remote(self, name: str) -> str:
        raise NotImplementedError("the stand-in hook is not written yet: say the address a clone of a world "
                                  "repository has (host_remote)")

    def host_repo(self, name: str):
        raise NotImplementedError("the stand-in hook is not written yet: say the Repo the layer addresses "
                                  "for a world repository (host_repo)")

    def host_serve(self, world: World) -> None:
        raise NotImplementedError("the stand-in hook is not written yet: serve the world as the host would "
                                  "(host_serve)")

    def host_seen(self, world: World) -> World:
        return world
'''

CONFORMANCE = '''"""The {name} pack held to the kit's conformance suite (keel/packkit/conformance.py)."""

import unittest

import suitefence

import {stem}_fence
import {stem}_layer
from keel.packkit.conformance import GuardContract, HostContract, VerbsContract
from standin import StandIn


class Host(StandIn, HostContract, unittest.TestCase):
    def host_layer(self):
        return {stem}_layer


class Guard(GuardContract, unittest.TestCase):
    def guard_pack(self):
        return suitefence.PACK

    def guard_policy(self):
        return {stem}_fence.POLICY


class Verbs(StandIn, VerbsContract, unittest.TestCase):
    def verbs_pack(self):
        return suitefence.PACK


if __name__ == "__main__":
    unittest.main()
'''

OPTIONS = [{"key": "repo", "label": "Repo", "type": "multiselect", "stored": "card", "options": [], "default": [],
            "help": "one or more of the space's repos; the first is the primary worktree"},
           {"key": "base", "label": "Base branch", "type": "text", "stored": "options",
            "placeholder": "the repo's default branch"}]

EXAMPLE = '''# A space on the {name} pack, as the install's config writes it.
[spaces.work]
pack = "{name}"
config_dir = "~/.claude"
'''


def stem(name: str) -> str:
    """The pack's module stem: its name with `-` as `_`, so `my-forge` writes `my_forge_layer.py`,
    which Python can import (r2.F3)."""
    return name.replace("-", "_")


def files(name: str) -> dict[str, str]:
    """Every file of a new kit pack, by its path in the pack."""
    title = name.replace("-", " ").replace("_", " ").title()
    fill = {"name": name, "stem": stem(name), "title": title, **{key: terms.DEFAULTS[key] for key in TERMS}}
    out = {"pack.toml": PACK_TOML.format(**fill), "guard": GUARD.format(**fill),
           f"{fill['stem']}_layer.py": LAYER.format(**fill), f"{fill['stem']}_ready.py": READY.format(**fill),
           f"{fill['stem']}_fence.py": FENCE.format(**fill), "rules/house.md": HOUSE.format(**fill),
           "rules/comments.md": COMMENTS.format(**fill), "tests/suitefence.py": SUITEFENCE.format(**fill),
           "tests/standin.py": STANDIN.format(**fill), "tests/test_conformance.py": CONFORMANCE.format(**fill),
           "options.json": json.dumps(OPTIONS, indent=2) + "\n", "config.example.toml": EXAMPLE.format(**fill)}
    out.update({verb: SHIM.format(verb=verb, **fill) for verb in VERBS})
    return out


def write(dest: Path, name: str) -> list[Path]:
    """Write the pack into `dest` (which must not be there yet); the paths written."""
    written = []
    for rel, text in files(name).items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if rel in VERBS or rel == "guard":
            path.chmod(0o755)
        written.append(path)
    return sorted(written)
