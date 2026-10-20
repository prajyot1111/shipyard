"""What this pack needs on the machine, each as a check with a reason and a fix: `ready`,
and the sign-in's rows for Keel's Logins list, `logins check`.

Five requirements, in the order a person meets them:

1. `git`: git is installed. It clones, pushes, and keeps the sign-in.
2. `address`: every repo of the space has an http or https address as its remote. That
   address is where the pack finds Gitea's API.
3. `sign-in`: git keeps a sign-in for each of those addresses, and Gitea accepts it.
4. `token`: the sign-in may do what the connection does. A password may; an access token
   made only for pushing may not say who it belongs to or read a pull request's comments.
5. `access`: the signed-in account may PUSH to each of those repositories. Seeing one is
   not enough: the first push to a repository the account can only read would fail.

`pack.toml` names each as a `[[requires]]` whose `check` is `./ready <name>`, with the
general reason and fix written there; `ready` alone prints all five with the SPECIFIC
sentences. The row, the space's repos and the clock are the kit's (`keel/packkit/ready.py`).

The pack never installs anything and never signs anyone in: a fix is text to copy and run.
It asks git for the sign-in only to make the one request that says whether Gitea accepts
it, and prints nothing of it but the account's name, which Gitea gives.
"""

import shutil
import time
from pathlib import Path

import gt_layer
from gt_layer import ScopeMissing
from keel.packkit import card as gc
from keel.packkit import pack
from keel.packkit import ready as kit
from keel.packkit.errors import HostError, Missing, NotFound, SignedOut
from keel.packkit.rest import MISSING, host_of

NAMES = ("git", "address", "sign-in", "token", "access")
INSTALL = ("Install git, then check again. On macOS: `xcode-select --install`. On Linux: `sudo apt install "
           "git` (Debian, Ubuntu) or `sudo dnf install git` (Fedora). Shipyard never installs it for you.")
SIGN_IN = ("In a terminal, in the repo's folder, run `git fetch`. If git asks for a user name and password, "
           "give your Gitea user name and password, or an access token made in Gitea under Settings, "
           "Applications, in place of the password. git keeps it when a credential helper is set (`git config "
           "--global credential.helper` prints one); set your system's helper first if it prints nothing. "
           "Then check again.")
NO_GIT = "git is not installed. Shipyard uses it for every repo, and it keeps the sign-in this connection uses."
NO_ANSWER = "Check again in a moment. This says nothing about your {what}: Gitea did not answer the question."

row = kit.row


def installed() -> dict:
    if shutil.which("git"):
        return row("git", True, "git is installed.")
    return row("git", False, NO_GIT, INSTALL)


def no_git(name: str, what: str) -> dict | None:
    return None if shutil.which("git") else row(name, False, f"git is not installed yet, so {what}.", INSTALL)


def address() -> dict:
    missing = no_git("address", "no repo's address can be read")
    if missing:
        return missing
    on, off = kit.on_host()
    if off:
        path, why = off[0]
        return row("address", False,
                   f"{path.name} has no address this connection can use: {why}.",
                   f"Point its remote at the repo's http or https address in Gitea: `git -C {path} remote "
                   f"set-url origin https://HOST/OWNER/REPO.git`. If it does not live on a Gitea, keep its "
                   f"work on this machine instead and push when you say.")
    if not on:
        return row("address", True, "This space has no repo yet, so there is no address to check.")
    return row("address", True, "Every repo's remote is an http or https address.")


def signed_in() -> dict:
    """Each Gitea the space's repos live on, asked who git's sign-in is: one request each,
    inside one budget."""
    missing = no_git("sign-in", "there is no sign-in to check")
    on, _ = ([], None) if missing else kit.on_host()
    if missing or not on:
        return missing or row("sign-in", True, "This space has no repo with a Gitea address yet, so there is no "
                                               "sign-in to check.")
    until, left = kit.clock()
    names = {}
    for _, repo in on:
        if repo.base in names:
            continue
        if time.monotonic() > until:
            return row("sign-in", False, f"There was no time to ask {gt_layer.host(repo)} who is signed in.",
                       "Check again.")
        try:
            names[repo.base] = gt_layer.account(repo, timeout=left())
        except SignedOut:
            return row("sign-in", False,
                       f"git keeps no sign-in for {gt_layer.host(repo)} that Gitea accepts. Shipyard opens pull "
                       f"requests as you, so Gitea has to know who you are.", SIGN_IN)
        except ScopeMissing:
            names[repo.base] = ""       # Gitea knew the token: it is a sign-in. What it may do is `token`'s to say
        except HostError as error:
            return row("sign-in", False, f"The sign-in for {gt_layer.host(repo)} could not be checked: {error}.",
                       NO_ANSWER.format(what="sign-in"))
    said = ", ".join(f"{name or 'an account it may not name'} on {host_of(base)}" for base, name in names.items())
    return row("sign-in", True, f"git is signed in to Gitea as {said}.")


def token_fix(repo) -> str:
    """How to swap the token git keeps for one that is allowed enough, with this Gitea's address."""
    scopes = gt_layer.SCOPES
    return ("In Gitea, open Settings, then Applications, and make an access token allowed "
            + ", ".join(scopes[:-1]) + " and " + scopes[-1] + ". Then make git forget the one it keeps: "
            "`printf 'url=" + repo.base + "\\n\\n' | git credential reject`. Then run `git fetch` in the repo's "
            "folder and give your user name, and the new token as the password. Then check again.")


def token() -> dict:
    """Whether the sign-in may do what the connection does. A password may do all its
    account may. An access token may do only what it was made for, so Gitea is asked the two
    things a token made for pushing alone is refused: who is signed in (`read:user`), and a
    pull request's general comments, which Gitea keeps as an issue's (`read:issue`). Whether
    it may also POST such a comment (`write:issue`) cannot be asked without posting one; a
    token that may only read them is refused at the user's first Ship, in the same words."""
    missing = no_git("token", "there is no sign-in to check")
    on, _ = ([], None) if missing else kit.on_host()
    if missing or not on:
        return missing or row("token", True, "This space has no repo with a Gitea address yet, so there is "
                                             "nothing to ask.")
    until, left = kit.clock()
    asked = set()
    for _, repo in on:
        if time.monotonic() > until:
            return row("token", False, f"There was no time to ask Gitea what the sign-in for "
                                       f"{gt_layer.host(repo)} may do.", "Check again.")
        try:
            if repo.base not in asked:
                asked.add(repo.base)
                gt_layer.account(repo, timeout=left())
            gt_layer.conversation_reach(repo, timeout=left())
        except SignedOut:
            return row("token", False, f"git keeps no sign-in for {gt_layer.host(repo)} that Gitea accepts, so "
                                       f"what it may do cannot be asked.", SIGN_IN)
        except ScopeMissing as error:
            return row("token", False,
                       f"The sign-in git keeps for {gt_layer.host(repo)} is an access token that is not allowed "
                       f"{' or '.join(error.needs)}. With it Shipyard can push and open pull requests, but cannot "
                       f"read or answer your teammates' comments, or tell which replies are already yours.",
                       token_fix(repo))
        except HostError as error:
            return row("token", False, f"What the sign-in for {gt_layer.host(repo)} may do could not be checked: "
                                       f"{error}.", NO_ANSWER.format(what="sign-in"))
    return row("token", True, "The sign-in may read who you are and the comments on pull requests.")


def who(repo, clock: float) -> str:
    try:
        return gt_layer.account(repo, timeout=clock) or "the signed-in account"
    except HostError:
        return "the signed-in account"


def access() -> dict:
    """Each repo of the space, asked of Gitea inside one budget: every call here, the
    account's name included, gets what is left of it and never more than the kit's call clock."""
    missing = no_git("access", "access cannot be checked")
    on, _ = ([], None) if missing else kit.on_host()
    if missing or not on:
        return missing or row("access", True, "This space has no repo with a Gitea address yet, so there is "
                                              "nothing to see.")
    until, left = kit.clock()
    for _, repo in on:
        if time.monotonic() > until:
            return row("access", False, f"There was no time to ask Gitea about {repo}.", "Check again.")
        try:
            may = gt_layer.access(repo, timeout=left())
        except SignedOut:
            return row("access", False, f"git has no sign-in Gitea accepts, so Gitea cannot say who may see {repo}.",
                       SIGN_IN)
        except NotFound:
            account = who(repo, left())
            return row("access", False, f"You are signed in to Gitea as {account}, which cannot see {repo}.",
                       f"Ask the owner of {repo} to give {account} access, or sign in to {gt_layer.host(repo)} "
                       f"as an account that has it.")
        except HostError as error:
            return row("access", False, f"Access to {repo} could not be checked: {error}.",
                       NO_ANSWER.format(what="account"))
        if may != "push":
            account = who(repo, left())
            return row("access", False, f"You are signed in to Gitea as {account}, which can read {repo} but "
                                        f"cannot push to it.",
                       f"Ask the owner of {repo} to give {account} write access, or sign in to "
                       f"{gt_layer.host(repo)} as an account that has it.")
    return row("access", True, "The signed-in account may push to " + ", ".join(str(repo) for _, repo in on) + ".")


CHECKS = {"git": installed, "address": address, "sign-in": signed_in, "token": token, "access": access}


def rows() -> list[dict]:
    return [CHECKS[name]() for name in NAMES]


# ----- the Logins list -----

WHERE = "git's own credential helper on this machine (Shipyard reads it only to ask Gitea, and keeps none)"
RENEW = "git fetch"


def hosts() -> dict:
    """{Gitea address: one repository on it} over every space on this pack."""
    found = {}
    cfg = gc.keel_config()
    for name in gc.on_pack(cfg):
        space = cfg.spaces[name]
        remote = getattr(space, "remote", None) or "origin"
        for path in space.repos.values():
            repo, _ = gc.clone_repo(Path(path), remote)
            if repo:
                found.setdefault(repo.base, repo)
    return found


def login_row(repo) -> dict:
    host = host_of(repo.base)
    made = {"id": f"codehost-{host}", "label": f"Code host sign-in ({host}, kept by git)", "where": WHERE}
    try:
        gt_layer.account(repo)
    except Missing as error:
        return dict(made, state="missing", why=str(error), fix=INSTALL)
    except SignedOut as error:
        return dict(made, state="expired", why=str(error), fix=RENEW)
    except ScopeMissing:
        # Gitea knows the token, so the sign-in is good; what it may do is the `token` check's to say
        return dict(made, state="good", fix=RENEW,
                    why="It is an access token that may not say who it belongs to: see the Gitea token check.")
    except HostError as error:
        return dict(made, state="unknown", why=str(error)[:200], fix=RENEW)
    return dict(made, state="good", why="", fix=RENEW)


def login_rows() -> list[dict]:
    """`[{id, label, state, why, where, fix}]`, one row per Gitea the pack's spaces use: the
    sign-in git keeps as `good`, `expired` (git has none Gitea accepts), `missing` (git is
    not installed) or `unknown` (it could not be asked, which Keel never reads as expired)."""
    if not shutil.which("git"):
        # with no git no repo's address can be read, so there is one row and it says why
        return [{"id": "codehost", "label": "Code host sign-in (kept by git)", "where": WHERE, "state": "missing",
                 "why": MISSING.format(name=pack.host().name), "fix": INSTALL}]
    return [login_row(repo) for repo in hosts().values()]
