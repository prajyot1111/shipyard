"""The one seam to GitHub: `gh`, its command line tool, run as a subprocess.

Every call the pack makes to GitHub goes through `run`: `gh` with a clock on it, never a
prompt, and its answer read as text or JSON (the kit's `cli.py` runs it). gh holds the
sign-in. This pack asks gh to do things as the signed-in account and never asks it for the
credential behind that: nothing here reads, prints or stores one, and nothing about the
account is written anywhere but a verb's own answer.

A call that fails is a `GithubError` whose message is ONE sentence: what was asked, and
gh's own words cleaned of colour, usage text and line breaks. Two failures have a class of
their own, because a requirement and a login row answer them differently: gh is not
installed (`GhMissing`), and gh is not signed in (`GhSignedOut`). GitHub's not-found answer
is `GhNotFound`. Each is the kit's own error (`keel/packkit/errors.py`) under its old name.
"""

import os
import re

from keel.packkit import cli
from keel.packkit.errors import HostError, Missing, NotFound, SignedOut

HOST = "github.com"
SECONDS = cli.SECONDS   # one call's clock; a verb makes a handful, each inside the engine's own
MISSING = ("gh, GitHub's command line tool, is not installed on this machine, so nothing can "
           "be asked of GitHub")
SIGNED_OUT = "gh is not signed in to GitHub: run `gh auth login` in a terminal, then try again"
# gh's words for a missing or refused sign-in, on any command
NO_LOGIN = re.compile(r"gh auth login|not logged in(?:to)?|authentication (?:failed|required)|"
                      r"bad credentials|HTTP 401", re.I)
# GitHub's own words for "there is no such thing, or not one you may see": the REST answer
# and the GraphQL one. A rate limit, a server error and the network say none of them.
NOT_FOUND = re.compile(r"HTTP 404|Could not resolve to an? ", re.I)

GithubError = HostError


class GhMissing(Missing):
    """gh is not on this machine's path."""


class GhSignedOut(SignedOut):
    """gh has no working sign-in for github.com."""


class GhNotFound(NotFound):
    """GitHub says what was asked for does not exist, or is not visible to this account."""


def environment() -> dict:
    """gh never prompts, never colours and never stops to say an update is out."""
    return dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1",
                CLICOLOR="0")


def sentence(text: str) -> str:
    """gh's own message as one plain sentence."""
    return cli.sentence(text, "gh")


def refusal(said: str, failed: str) -> HostError | None:
    """The class a failure of gh's is: signed out, not found, or neither."""
    if NO_LOGIN.search(said):
        return GhSignedOut(SIGNED_OUT)
    return GhNotFound(failed) if NOT_FOUND.search(said) else None


def run(*args: str, stdin: str | None = None, timeout: int = SECONDS, cwd=None) -> str:
    """`gh <args>`: its stdout. `stdin` is handed to it when given (a body, a JSON input);
    without one it is given none, so it can never wait on the verb's own."""
    return cli.run("gh", *args, stdin=stdin, timeout=timeout, cwd=cwd, env=environment(), host="GitHub",
                   missing=GhMissing(MISSING), refusal=refusal)


def read(*args: str, **kwargs):
    """A call that answers one JSON value."""
    return cli.parsed(run(*args, **kwargs), cli.named("gh", args))


def api(path: str) -> list[dict]:
    """Every row of a paged listing of GitHub's API, through `gh api --paginate`: gh prints
    one JSON array per page, one after another, and this reads them all as one list."""
    return cli.rows(run("api", "--hostname", HOST, "--paginate", path), f"gh api {path}")
