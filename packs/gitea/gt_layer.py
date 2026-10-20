"""The Gitea pack's host layer (`keel/packkit/layer.py` is the contract): pull requests on a
Gitea, through its API (`/api/v1`) at the address each repo is cloned from, with the sign-in
git keeps for that address (the kit's `rest.py`).

A repository is a `Repo`: its `owner/repo`, with `base`, the address its Gitea is served at
(a Gitea may live under a path), and `clone`, where git is asked for the sign-in. A pull
request comes back in the kit's words: `open`, `merged` or `declined` (closed without
merging), or `unknown`. `own` is true only when Gitea says the head branch is in the
repository itself (the head's and the base's repository are one).

**A draft is a title.** Gitea has no draft of its own kind: a pull request whose title starts
with a work-in-progress mark (`WIP:` or `[WIP]` unless the Gitea is set up with others) is
one, and Gitea refuses to merge it. So a draft is opened with `WIP: ` before the card's
title, and marking it ready takes the mark off; one Gitea still calls a draft after that is
refused, since saying "ready" would be untrue.

**Gitea's words, in the kit's.** Gitea lists a line's comments under the review each came in
and does not say which answers which, so the comments on one line of one file are one
conversation, in the order they were said, each after the first naming the first as its
parent; a reply is posted under the comment it answers. A bot is a name ending `[bot]` or
one of Gitea's own system accounts (a negative id). A line comment someone resolved has a
`resolver`. The head's checks are its commit statuses (a warning is not a failure).

**The sign-in.** When it is an access token, it may do only what it was made for. Gitea
refuses a call it was not made for in its own words, which this layer reads as
`ScopeMissing`, whose sentence says which token to make (`SCOPES`).
"""

import re
from urllib.parse import urlsplit

from keel.packkit import VERSION
from keel.packkit.errors import HostError, NotFound, OutsideChange
from keel.packkit.layer import GENERAL, LINES, PARTS, REVIEWS, HostConfig, Repo
from keel.packkit.rest import Rest, host_of, part

KIT = VERSION
API = Rest("Gitea")
UNKNOWN = "unknown"
DRAFT = "WIP: "
# Gitea's own default marks (`[repository.pull-request] WORK_IN_PROGRESS_PREFIXES`), any case
DRAFT_MARK = re.compile(r"^\s*(?:WIP:|\[WIP\])\s*", re.I)
FAILED = ("failure", "error")
WAITING = ("pending",)
REVIEW_STATES = {"APPROVED": "approved", "REQUEST_CHANGES": "changes_requested", "PENDING": "pending",
                 "REQUEST_REVIEW": "pending"}
EVENTS = {"approve": "APPROVED", "changes": "REQUEST_CHANGES"}
REFUSED_AS_WRITTEN = 422
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
NO_SUCH_METHOD = 405
# Gitea's own sentence for a token made without a scope the call needs
SCOPE = re.compile(r"required scope\(s\), required=\[([^\]]*)\](?:, token scope=(\S+))?")
SCOPES = ("write:repository", "write:issue", "read:user")
NEW_TOKEN = ("in Gitea, under Settings, Applications, make an access token allowed " + ", ".join(SCOPES[:-1])
             + " and " + SCOPES[-1] + ", and give it to git in place of this one")
NOT_HTTP = ("is not an http or https address, and this connection reads Gitea's API at the address the "
            "repo is cloned from")


class ScopeMissing(HostError):
    """Gitea accepts the sign-in, an access token, and the token may not do what was asked.
    `needs` is what Gitea asked for, in its own words (`read:issue`)."""

    needs: tuple[str, ...] = ()


# ----- addresses, asked of nobody -----

def shown(address: str) -> str:
    """An address as a person may read it: a user name or password written into it is left out."""
    return re.sub(r"(?<=://)[^/@]*@", "", (address or "").strip())


def address(remote_url: str, clone=None) -> Repo | None:
    """The repository an http(s) address names: its last two parts are `owner/repo`, and what
    stands before them is where Gitea is served. None for any other address: ssh, a path on
    this disk, or one with no owner and repo."""
    try:
        parts = urlsplit((remote_url or "").strip())
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path.rstrip("/").removesuffix(".git")
    names = [name for name in path.split("/") if name]
    if len(names) < 2:
        return None
    under = "/".join(names[:-2])
    base = f"{parts.scheme}://{parts.hostname}{port}" + (f"/{under}" if under else "")
    return Repo("/".join(names[-2:]), base, clone)


def url(repo, number: int) -> str:
    return f"{repo.base}/{repo}/pulls/{int(number)}"


HOST = HostConfig(
    name="Gitea", on="in Gitea", address=address, pr_url=url,
    elsewhere=lambda found: f"its address {shown(found)} {NOT_HTTP}",
    draft_note=" Its title starts with `WIP:`, which is what a draft is in Gitea: leave that mark alone.",
    ready="gt_ready", guard="gt_fence")


# ----- one call -----

def scope_missing(error: HostError) -> HostError:
    """A 403 that is Gitea refusing a token's scope, as `ScopeMissing`; any other error as it is."""
    found = SCOPE.search(getattr(error, "said", "") or "") if error.status == 403 else None
    if not found:
        return error
    needs = tuple(one.strip() for one in found.group(1).split(",") if one.strip())
    has = f" (it is allowed {found.group(2).rstrip('.,')})" if found.group(2) else ""
    what = str(error).split(" failed (", 1)[0]
    made = ScopeMissing(f"{what} was refused: the sign-in git keeps is an access token that is not allowed "
                        f"{' or '.join(needs)}{has}; {NEW_TOKEN}")
    made.needs, made.status = needs, error.status
    return made


def call(base: str, method: str, path: str, **kwargs):
    try:
        return API.call(base, method, path, **kwargs)
    except HostError as error:
        raise scope_missing(error) from None


def pages(base: str, path: str, query: dict | None = None, **kwargs) -> list[dict]:
    try:
        return API.pages(base, path, query, **kwargs)
    except HostError as error:
        raise scope_missing(error) from None


def listed(base: str, path: str, **kwargs) -> list[dict]:
    found = call(base, "GET", path, **kwargs)
    return [row for row in found if isinstance(row, dict)] if isinstance(found, list) else []


def where(repo) -> str:
    owner, name = str(repo).split("/", 1)
    return f"repos/{part(owner)}/{part(name)}"


def ask(repo, method: str, path: str = "", **kwargs):
    return call(repo.base, method, f"{where(repo)}/{path}".rstrip("/"), cwd=repo.clone, **kwargs)


# ----- one pull request -----

def state_of(found: dict) -> str:
    if found.get("merged") is True:
        return "merged"
    return {"open": "open", "closed": "declined"}.get(str(found.get("state") or "").lower(), UNKNOWN)


def drafted(found: dict) -> bool:
    """A draft when Gitea says so, or when its title carries the mark (a Gitea that sends no
    `draft` field still refuses to merge one)."""
    return bool(found.get("draft")) or bool(DRAFT_MARK.match(str(found.get("title") or "")))


def shaped(found: dict, repo) -> dict:
    number = int(found["number"])
    head, base = found.get("head") or {}, found.get("base") or {}
    own = head.get("repo_id") is not None and head.get("repo_id") == base.get("repo_id")
    return {"id": number, "url": found.get("html_url") or url(repo, number), "draft": drafted(found),
            "title": found.get("title"), "state": state_of(found), "head": head.get("sha"),
            "branch": head.get("ref"), "base": base.get("ref"), "own": own,
            "author": (found.get("user") or {}).get("login"), "updated": found.get("updated_at")}


def open_ones(repo) -> list[dict]:
    """Every open pull request of the repository, as Gitea gives them."""
    return pages(repo.base, f"{where(repo)}/pulls", {"state": "open"}, cwd=repo.clone)


def find_open(repo, branch: str) -> dict | None:
    """The OPEN pull request from this branch OF THIS REPOSITORY, or None: a branch of the
    same name in someone's fork is passed over."""
    shapes = (shaped(row, repo) for row in open_ones(repo))
    return next((one for one in shapes if one["branch"] == branch and one["own"]), None)


def raw(repo, number: int) -> dict:
    found = ask(repo, "GET", f"pulls/{int(number)}")
    if not isinstance(found, dict) or "number" not in found:
        raise HostError(f"Gitea answered nothing that reads as pull request #{int(number)} of {repo}")
    return found


def get(repo, number: int, sight: bool = False) -> dict:
    return shaped(raw(repo, number), repo)


def open_pr(repo, title: str, branch: str, base: str, body: str, draft: bool = True, cwd=None) -> dict:
    """Open the pull request from `branch` into `base`; a draft carries the mark in its title."""
    title = title if not draft or DRAFT_MARK.match(title) else DRAFT + title
    made = ask(repo, "POST", "pulls", body={"head": branch, "base": base, "title": title, "body": body})
    if not isinstance(made, dict) or "number" not in made:
        raise HostError(f"Gitea did not say which pull request it opened from {branch}")
    return shaped(made, repo)


def set_ready(repo, number: int) -> None:
    """Take the draft mark off the title; refused when Gitea still calls it a draft after."""
    title = str(raw(repo, number).get("title") or "")
    bare = title
    while DRAFT_MARK.match(bare):
        bare = DRAFT_MARK.sub("", bare, count=1)
    after = ask(repo, "PATCH", f"pulls/{int(number)}", body={"title": bare or title}) if bare != title else None
    still = drafted(after if isinstance(after, dict) else raw(repo, number))
    if still:
        raise HostError(f"Gitea still calls pull request #{int(number)} of {repo} a draft (its title is "
                        f"{(bare or title)!r}): take the work-in-progress mark off its title in Gitea")


def set_body(repo, number: int, body: str) -> None:
    ask(repo, "PATCH", f"pulls/{int(number)}", body={"body": body})


# ----- what people said on it -----

def is_bot(row: dict) -> bool:
    who = row.get("user") or {}
    system = isinstance(who.get("id"), int) and who["id"] < 0       # Gitea's own accounts (its Actions bot)
    return system or str(who.get("login") or "").lower().endswith("[bot]")


def comment_of(row: dict, kind: str = "g") -> dict:
    return {"kind": kind, "id": int(row["id"]), "author": (row.get("user") or {}).get("login"), "bot": is_bot(row),
            "body": row.get("body") or "", "at": row.get("created_at"),
            "updated": row.get("updated_at") or row.get("created_at"), "path": None, "line": None, "parent": None,
            "reply_to": int(row["id"]), "resolved": False}


def line_of(row: dict) -> int | None:
    """Gitea's `position` is the line of the file; `original_position` where it was."""
    return row.get("position") or row.get("original_position") or None


def conversations(lines: list[dict]) -> dict[int, int | None]:
    """{comment id: the first comment of its conversation, None for that first one}."""
    first, out = {}, {}
    for row in sorted(lines, key=lambda one: (str(one.get("created_at") or ""), int(one["id"]))):
        place = (row.get("path"), line_of(row))
        out[int(row["id"])] = first.get(place) if place[0] and place[1] else None
        first.setdefault(place, int(row["id"]))
    return out


def review_of(row: dict) -> dict:
    state = str(row.get("state") or "").upper()
    return {"id": row.get("id"), "author": (row.get("user") or {}).get("login"), "bot": is_bot(row),
            "state": REVIEW_STATES.get(state, "commented"), "dismissed": bool(row.get("dismissed")),
            "body": row.get("body") or "", "at": row.get("submitted_at"), "url": row.get("html_url"),
            "comments_count": row.get("comments_count")}


def reviews(repo, number: int) -> list[dict]:
    return pages(repo.base, f"{where(repo)}/pulls/{int(number)}/reviews", cwd=repo.clone)


def review_comments(repo, number: int, submitted: list[dict]) -> list[dict]:
    """The comments on lines, asked of every review that has any."""
    found = []
    for one in submitted:
        if one.get("id") is not None and one.get("comments_count"):
            found += listed(repo.base, f"{where(repo)}/pulls/{int(number)}/reviews/{int(one['id'])}/comments",
                            cwd=repo.clone)
    return found


def said(repo, number: int, parts=PARTS) -> dict:
    """What was said on it, in the kit's shapes, reading only the `parts` asked for."""
    out = {GENERAL: [], LINES: [], REVIEWS: []}
    submitted = reviews(repo, number) if LINES in parts or REVIEWS in parts else []
    if REVIEWS in parts:
        out[REVIEWS] = [review_of(row) for row in submitted]
    if LINES in parts:
        rows = review_comments(repo, number, submitted)
        under = conversations(rows)
        out[LINES] = [dict(comment_of(row, "l"), path=row.get("path"), line=line_of(row),
                           parent=under.get(int(row["id"])), resolved=bool(row.get("resolver"))) for row in rows]
    if GENERAL in parts:
        out[GENERAL] = [comment_of(row) for row in listed(repo.base, f"{where(repo)}/issues/{int(number)}/comments",
                                                          cwd=repo.clone)]
    return out


def checks(repo, pr: dict) -> list[dict]:
    """The commit statuses on the change's head, as Gitea combines them."""
    if not pr.get("head"):
        return []
    found = ask(repo, "GET", f"commits/{part(pr['head'])}/status")
    rows = (found or {}).get("statuses") if isinstance(found, dict) else None
    out = []
    for one in rows or []:
        status = str(one.get("status") or "").lower()
        state = "failed" if status in FAILED else "running" if status in WAITING else "passed"
        out.append({"state": state, "name": one.get("context"), "url": one.get("target_url"),
                    "at": one.get("updated_at") or one.get("created_at")})
    return out


def comment(repo, number: int, text: str) -> None:
    ask(repo, "POST", f"issues/{int(number)}/comments", body={"body": text})


def reply(repo, number: int, under: int, text: str) -> None:
    """A reply under line comment `under`. A Gitea too old for its replies call has no
    such address, so there the reply is a review's comment on the same line of the same
    file, which Gitea shows in the same conversation."""
    try:
        ask(repo, "POST", f"pulls/{int(number)}/comments/{int(under)}/replies", body={"body": text})
        return
    except NotFound:
        pass
    except HostError as error:
        if error.status != NO_SUCH_METHOD:
            raise
    lines = said(repo, number, parts=(LINES,))[LINES]
    first = next((one for one in lines if one["id"] == int(under)), None)
    if first is None or not first["path"] or not first["line"]:
        raise NotFound(f"Gitea has no comment {int(under)} on a line of pull request #{int(number)} of {repo}")
    ask(repo, "POST", f"pulls/{int(number)}/reviews",
        body={"body": "", "event": "COMMENT", "comments": [{"path": first["path"], "new_position": first["line"],
                                                          "body": text}]})


def in_hunks(diff: str) -> dict[str, set[int]]:
    """{path: the lines of the file as the change leaves it that a hunk of the unified `diff`
    shows, added or context}: the lines GitHub takes a review comment on."""
    out, path, new, old = {}, None, 0, 0
    for row in (one.removesuffix("\r") for one in diff.split("\n")):    # a form feed ends no line
        if new > 0 or old > 0:
            mark = row[:1]
            if mark in (" ", "+", ""):
                out.setdefault(path, set()).add(line)
                line, new = line + 1, new - 1
            old -= mark in (" ", "-", "")
            continue
        if row.startswith("+++ "):
            name = row[4:].strip().strip('"')
            path = name[2:] if name.startswith("b/") else None
        elif hunk := HUNK.match(row):
            line, new = int(hunk.group(3)), int(hunk.group(4) or 1)
            old = int(hunk.group(2) or 1)
    out.pop(None, None)
    return out


def changed_lines(repo, number: int) -> dict[str, set[int]]:
    return in_hunks(ask(repo, "GET", f"pulls/{int(number)}.diff", text=True) or "")


def post_review(repo, number: int, body: str, verdict: str, comments: list[dict], head) -> dict:
    """ONE review: its words, its verdict and its comments on lines (`new_position`, the line
    of the file as the change leaves it), in one call. Gitea posts a comment on a line the
    change does not touch (2026-10-10), so the change's diff is read first and such a
    comment is `OutsideChange`, with nothing posted."""
    lines = changed_lines(repo, number) if comments else {}
    away = [f"{one['path']}:{int(one['line'])}" for one in comments
            if int(one["line"]) not in lines.get(one["path"], ())]
    if away:
        raise OutsideChange(f"{', '.join(away)} is not a line pull request #{int(number)} of {repo} changes")
    payload = {"body": body, "event": EVENTS.get(verdict, "COMMENT"),
               "comments": [{"path": one["path"], "new_position": int(one["line"]), "body": one["text"]}
                            for one in comments]}
    if head:
        payload["commit_id"] = head
    try:
        made = ask(repo, "POST", f"pulls/{int(number)}/reviews", body=payload)
    except HostError as error:
        if error.status == REFUSED_AS_WRITTEN:
            raise OutsideChange(str(error)) from None
        raise
    made = made if isinstance(made, dict) else {}
    return {"id": made.get("id"), "url": made.get("html_url"), "inline_count": len(comments)}


# ----- lists -----

def listed_pr(row: dict, repo) -> dict:
    return dict(shaped(row, repo), body=row.get("body") or "", created=row.get("created_at"))


def review_requests(repo) -> list[dict]:
    """Every open pull request that names the signed-in account among its requested
    reviewers and that it did not write (Gitea takes a reviewer off that list once they
    review)."""
    me = account(repo)
    asks = lambda row: (bool(me) and me in {(one or {}).get("login") for one in row.get("requested_reviewers") or []}  # noqa: E731
                        and (row.get("user") or {}).get("login") != me)
    return [listed_pr(row, repo) for row in open_ones(repo) if asks(row)]


def mine(repo) -> list[dict]:
    """The signed-in account's open pull requests from the repository's own branches."""
    me = account(repo)
    return [one for one in (shaped(row, repo) for row in open_ones(repo)) if me and one["author"] == me and one["own"]]


# ----- the repository and the account -----

def visible(repo, timeout: float = 30) -> dict:
    found = ask(repo, "GET", timeout=timeout)
    return found if isinstance(found, dict) else {}


def default_branch(repo, timeout: float = 30) -> str:
    name = visible(repo, timeout).get("default_branch")
    if not name:
        raise HostError(f"Gitea named no default branch for {repo}")
    return str(name)


def protected(repo, branch: str) -> bool:
    """A branch Gitea has never heard of is not protected; any other failure is raised."""
    try:
        found = ask(repo, "GET", f"branches/{part(branch)}")
    except NotFound:
        return False
    return bool((found or {}).get("protected")) if isinstance(found, dict) else False


def account(repo=None, timeout: float = 30, base: str | None = None, cwd=None) -> str:
    """The signed-in account's name on the repository's Gitea (or the one at `base`)."""
    base, cwd = (base, cwd) if base else (repo.base, repo.clone)
    found = call(base, "GET", "user", timeout=timeout, cwd=cwd)
    return str((found or {}).get("login") or "") if isinstance(found, dict) else ""


def signed_in(repo=None, timeout: float = 30) -> None:
    account(repo, timeout)


def access(repo, timeout: float = 30) -> str:
    may = (visible(repo, timeout).get("permissions") or {}).get("push")
    return "push" if may is True else "read"


def conversation_reach(repo, timeout: float = 30) -> None:
    """Raises unless the sign-in may read the general comments of the repository's pull
    requests, which Gitea keeps as issues' (one row is asked for and none is read)."""
    call(repo.base, "GET", f"{where(repo)}/issues/comments", query={"limit": 1, "page": 1}, timeout=timeout,
         cwd=repo.clone)


def host(repo) -> str:
    return host_of(repo.base)
