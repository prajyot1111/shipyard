"""The host layer contract: what a pack on the kit writes, and the shapes it hands back.

A layer is ONE module in the pack's folder (the GitHub pack's `gh_layer.py`). It declares
`KIT`, the kit version it was written for, and `HOST`, a `HostConfig`; and it has the
operations below, each taking a `Repo` and raising only the kit's errors (`errors.py`). The
kit never starts a host process or opens a socket itself: it calls the layer.

`check_layer` names, in one sentence, a layer that lacks an operation, has no `HOST`, or was
written for another kit.

**A repository** is a `Repo`: it prints and compares as `owner/repo`, and carries `base`, the
address its host is served at, and `clone`, the clone it was read from. `HOST.address` reads
one from a remote's address and the clone, and asks nothing of the host (`act links` stays
off the network).

**The operations** (`OPERATIONS`):

- `find_open(repo, branch)`: the OPEN change from this branch of the repository itself, or
  None; a fork's branch of the same name is never it.
- `get(repo, n, sight=False)`: one change, `PR` below. `sight` says the kit is about to read
  its checks too, so a host that answers both in one call may.
- `open_pr(repo, title, branch, base, body, draft=True, cwd=None)`: a new change, as `get`.
- `set_ready(repo, n)`, `set_body(repo, n, body)`, `comment(repo, n, text)`,
  `reply(repo, n, under, text)` (`under` is a line comment's `reply_to`).
- `said(repo, n, parts=PARTS)`: `{"general": [C], "lines": [C], "reviews": [R]}`, reading
  only the `parts` asked for (`RESOLVED` marks which line comments are resolved).
- `checks(repo, pr)`: the checks on the change's head, `[{state, name, url, at}]` with the
  state `failed`, `running` or `passed`.
- `post_review(repo, n, body, verdict, comments, head)`: ONE review, `verdict` one of
  `approve`, `changes`, `comment`, `comments` `[{path, line, text}]`; answers `{id, url,
  inline_count}`, and raises `OutsideChange`, posting nothing, for a finding on a line the
  change does not touch, whether or not the host would refuse that line itself.
- `review_requests(repo)`: the open changes that ask the signed-in account for its review,
  each `PR` with `body` and `created`.
- `mine(repo)`: the signed-in account's open changes, each `PR`.
- `default_branch(repo, timeout=...)`, `protected(repo, branch)` (a branch the host never
  heard of is not), `account(repo, timeout=...)` (who is signed in), `signed_in(repo,
  timeout=...)` (raises unless), `access(repo, timeout=...)`: `"push"` or `"read"`, or
  `NotFound`.

**The shapes.**

- `PR`: `{id, url, draft, title, state, head, branch, base, own, author, updated}`, the state
  `open`, `merged`, `declined` (closed without merging) or `unknown`, which no caller reads
  as open. `own` is true only when the host says the head branch is the repository's own.
- `C`, a comment: `{kind, id, author, bot, body, at, updated, path, line, parent, reply_to,
  resolved}`. `kind` is `g` (general), `l` (on a line) or `r` (a review's words); `parent` is
  the id of the line comment it answers, `reply_to` the id a reply to it is posted under.
- `R`, a review: `{id, author, bot, state, dismissed, body, at, comments_count}`, the state
  `approved`, `changes_requested`, `commented` or `pending`.
"""

from dataclasses import dataclass, field
from typing import Callable

from keel.packkit import VERSION
from keel.packkit.errors import HostError

OPERATIONS = ("find_open", "get", "open_pr", "set_ready", "set_body", "said", "checks", "comment", "reply",
              "post_review", "review_requests", "mine", "default_branch", "protected", "account", "signed_in",
              "access")
GENERAL, LINES, RESOLVED, REVIEWS = "general", "lines", "resolved", "reviews"
PARTS = (LINES, RESOLVED, REVIEWS, GENERAL)
UNKNOWN = "unknown"
VERDICTS = ("approve", "changes", "comment")

# What a layer may leave to the kit's own words. A layer's `HostConfig.say` lays its own over
# these; `{host}` is its name and `{change}` the pack's word for a change.
SAY = {
    "sign_git_in": (" (git has no sign-in for this remote here: fetch or push once in a terminal so git asks "
                    "for it and keeps it, then Ship again)"),
    "no_account": ("{host} could not say which account is signed in ({why}), so the replies already posted "
                   "cannot be told from the rest: nothing was pushed and no reply was posted; try again"),
    "review_reads": ("Read the change with git, in the worktree: `git diff {remote}/{base}...HEAD`, `git log "
                     "{remote}/{base}..HEAD`, and the files themselves. Never ask {host} yourself and never "
                     "comment on, review, approve or merge the {change} by hand: Approve outcome posts what "
                     "the user keeps."),
}


class LayerError(HostError):
    """A layer the kit cannot run: it says why in one sentence."""


class Repo(str):
    """A repository on a code host: `owner/repo`, which is how it prints and compares, with
    `base`, the address its host is served at (no user name, no password, no trailing slash),
    and `clone`, the clone it was read from."""

    base: str = ""
    clone = None

    def __new__(cls, name: str, base: str = "", clone=None):
        made = super().__new__(cls, name)
        made.base, made.clone = base, clone
        return made


def _none(*_args):
    return None


@dataclass(frozen=True)
class HostConfig:
    """What the kit needs to know of a host that is not a call to it.

    `name` is every sentence's word for the host and `on` how one says a thing is there ("on
    GitHub", "in Gitea"). `address(remote_url, clone)` is the `Repo` a remote's address
    names, or None; `elsewhere(address)` says why an address is not one. `pr_url(repo, n)` is
    a change's address, built without asking. `pull_head_ref` is the ref a change's head is
    fetched from. `draft_note` is what a house is told a draft is, after "records each on the
    card." (empty when a draft is the host's own kind). `say` lays sentences over `SAY`;
    `ready` and `guard` name the pack's requirement module and its guard's policy module."""

    name: str
    on: str
    address: Callable
    pr_url: Callable
    elsewhere: Callable = field(default=lambda address: f"its address is {address}, which is not one this pack reads")
    pull_head_ref: str = "refs/pull/{n}/head"
    draft_note: str = ""
    say: dict = field(default_factory=dict)
    ready: str = ""
    guard: str = ""

    def said(self, key: str, **fill) -> str:
        """One of the host's sentences (`say` over the kit's `SAY`), filled."""
        text = self.say.get(key, SAY.get(key, ""))
        return text.format(host=self.name, **fill) if fill or "{host}" in text else text


def check_layer(module, name: str = "") -> None:
    """Refuse, in one sentence, a layer the kit cannot run."""
    name = name or getattr(module, "__name__", "the")
    kit = getattr(module, "KIT", None)
    if kit != VERSION:
        said = f"pack kit {kit}" if kit is not None else "no pack kit (it declares no KIT)"
        raise LayerError(f"the {name} layer was written for {said}, and this Shipyard's pack kit is {VERSION}: "
                         f"bring the layer up to kit {VERSION}, or use the Shipyard it was written for")
    if not isinstance(getattr(module, "HOST", None), HostConfig):
        raise LayerError(f"the {name} layer has no HOST, the HostConfig that says what its host is called "
                         f"and how its addresses read")
    missing = [op for op in OPERATIONS if not callable(getattr(module, op, None))]
    if missing:
        listed = ", ".join(missing[:-1]) + (" and " if len(missing) > 1 else "") + missing[-1]
        raise LayerError(f"the {name} layer lacks {listed}, which the kit calls")


# ----- the shapes, as the kit reads them -----

def fold_checks(checks: list[dict]) -> dict:
    """The head's checks as one word: failed if any failed (with that one's name, address and
    time), running if any has not finished, passed if all did, none when nothing reports."""
    if not checks:
        return {"state": "none"}
    for one in checks:
        if one.get("state") == "failed":
            return {"state": "failed", "name": one.get("name"), "url": one.get("url"), "at": one.get("at")}
    if any(one.get("state") == "running" for one in checks):
        return {"state": "running"}
    return {"state": "passed"}
