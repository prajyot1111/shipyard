"""What this pack needs on the machine, each as a check with a reason and a fix: `ready`,
and the sign-in's row for Keel's Logins list, `logins check`.

Four requirements, in the order a person meets them:

1. `gh`: GitHub's command line tool is installed.
2. `sign-in`: gh is signed in to github.com.
3. `address`: every repo of the space has a github.com address as its remote.
4. `access`: the signed-in account may PUSH to each of those repositories (GitHub says its
   permission is write, maintain or admin). Seeing one is not enough: the first push to a
   repository the account can only read would fail.

`pack.toml` names each as a `[[requires]]` whose `check` is `./ready <name>` (exit 0 when
ready), with the general reason (`why`) and fix (`fix`) written there. `ready` alone prints
all four as JSON, `[{name, ok, why, fix}]`, with the SPECIFIC sentences: which account,
which repo, which address. The space's repos arrive as `KEEL_SPACE_REPOS`, the paths
joined by the path separator, as every pack's checks get them.

The pack never installs anything and never signs anyone in: a fix is text to copy and run.
It asks gh whether it is signed in and who as; it never asks for the credential. The row,
the space's repos and the clock are the kit's (`keel/packkit/ready.py`).
"""

import shutil
import time

import gh_cli
import gh_layer
from gh_cli import GithubError
from keel.packkit import ready as kit

NAMES = ("gh", "sign-in", "address", "access")
BUDGET = kit.BUDGET              # seconds for one requirement: the engine stops a check at ten
CALL_SECONDS = kit.CALL_SECONDS  # one gh call's clock here; two of them (the repo, then who) fit the budget
INSTALL = ("Install it, then check again. On macOS: `brew install gh`. On Linux: `sudo apt install gh` "
           "(Debian, Ubuntu) or `sudo dnf install gh` (Fedora), or the line for your system at "
           "https://github.com/cli/cli#installation. Shipyard never installs it for you.")
SIGN_IN = ("Run `gh auth login` in a terminal. Choose GitHub.com, then HTTPS, then sign in with "
           "your browser. Then check again.")
NO_GH = "gh, GitHub's command line tool, is not installed. Shipyard uses it to open pull requests as you."


row = kit.row


def installed() -> dict:
    if shutil.which("gh"):
        return row("gh", True, "gh is installed.")
    return row("gh", False, NO_GH, INSTALL)


def signed_in() -> dict:
    if not shutil.which("gh"):
        return row("sign-in", False, "gh is not installed yet, so there is no sign-in to check.", INSTALL)
    try:
        gh_layer.signed_in(timeout=CALL_SECONDS)
    except gh_cli.GhSignedOut:
        return row("sign-in", False, "gh is not signed in to GitHub. Shipyard opens pull requests as "
                                     "you, so GitHub has to know who you are.", SIGN_IN)
    except GithubError as error:
        return row("sign-in", False, f"The sign-in could not be checked: {error}.",
                   "Check again in a moment. If it stays this way, run `gh auth status` in a terminal.")
    return row("sign-in", True, "gh is signed in to GitHub.")


def address() -> dict:
    on, off = kit.on_host()
    if off:
        path, why = off[0]
        return row("address", False,
                   f"{path.name} is not a GitHub repository: {why}. This connection only works for "
                   f"repositories on github.com.",
                   f"If {path.name} lives on GitHub, point its remote there: `git -C {path} remote "
                   f"set-url origin https://github.com/OWNER/REPO.git`. If it lives somewhere else, "
                   f"keep its work on this machine instead and push when you say.")
    if not on:
        return row("address", True, "This space has no repo yet, so there is no address to check.")
    return row("address", True, "Every repo's remote is a github.com address.")


def who(clock: float) -> str:
    try:
        return gh_layer.account(timeout=clock) or "the signed-in account"
    except GithubError:
        return "the signed-in account"


def access() -> dict:
    """Each GitHub repo of the space, asked of GitHub inside one budget: every gh call here,
    the account's name included, gets what is left of it and never more than CALL_SECONDS."""
    on, _ = kit.on_host()
    if not on:
        return row("access", True, "This space has no GitHub repo yet, so there is nothing to see.")
    if not shutil.which("gh"):
        return row("access", False, "gh is not installed yet, so access cannot be checked.", INSTALL)
    until, left = kit.clock(BUDGET, CALL_SECONDS)
    for _, slug in on:
        if time.monotonic() > until:
            return row("access", False, f"There was no time to ask GitHub about {slug}.", "Check again.")
        try:
            may = gh_layer.access(slug, timeout=left())
        except gh_cli.GhSignedOut:
            return row("access", False, f"gh is not signed in, so GitHub cannot say who may see {slug}.", SIGN_IN)
        except gh_cli.GhNotFound:
            account = who(left())
            return row("access", False,
                       f"You are signed in to GitHub as {account}, which cannot see {slug}.",
                       f"Switch to an account that can see {slug} with `gh auth switch`, or sign in "
                       f"with one (`gh auth login`), or ask the owner of {slug} to give {account} access.")
        except GithubError as error:
            return row("access", False, f"Access to {slug} could not be checked: {error}.",
                       "Check again in a moment. This says nothing about your account: GitHub did "
                       "not answer the question.")
        if may != "push":
            account = who(left())
            return row("access", False,
                       f"You are signed in to GitHub as {account}, which can read {slug} but cannot "
                       f"push to it.",
                       f"Ask the owner of {slug} to give {account} write access, or switch to an "
                       f"account that has it with `gh auth switch`.")
    return row("access", True, "The signed-in account may push to " + ", ".join(slug for _, slug in on) + ".")


CHECKS = {"gh": installed, "sign-in": signed_in, "address": address, "access": access}


def rows() -> list[dict]:
    return [CHECKS[name]() for name in NAMES]


# ----- the Logins list -----

WHERE = "gh's own store on this machine (Shipyard reads and keeps no credential)"


def login_rows() -> list[dict]:
    """`[{id, label, state, why, where, fix}]`: gh's sign-in as `good`, `expired` (gh says
    it has none that works), `missing` (gh is not installed) or `unknown` (it could not be
    asked, which Keel never reads as expired)."""
    base = {"id": "github", "label": "GitHub sign-in (gh)", "where": WHERE}
    try:
        gh_layer.signed_in()
    except gh_cli.GhMissing as error:
        return [dict(base, state="missing", why=str(error), fix=INSTALL)]
    except gh_cli.GhSignedOut as error:
        return [dict(base, state="expired", why=str(error), fix="gh auth login")]
    except GithubError as error:
        return [dict(base, state="unknown", why=str(error)[:200], fix="gh auth status")]
    return [dict(base, state="good", why="", fix="gh auth login")]
