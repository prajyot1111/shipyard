"""The GitHub pack's host layer (`keel/packkit/layer.py` is the contract): pull requests on
github.com, each operation one `gh` call (`gh_cli.run`), or a few.

A repository is a `Repo` whose name is its `owner/repo` slug, always asked for on
github.com by name (`github.com/owner/repo`), so a `GH_HOST` in the environment never sends
a call elsewhere. A pull request comes back in the kit's words: `{id, url, draft, title,
state, head, branch, base, own}` with the state `open`, `merged` or `declined` (GitHub's
CLOSED: closed without merging), or `unknown` when GitHub names none of those. `own` is true
only when GitHub says the head branch is the repository's own (not cross-repository); a
missing answer is not a yes.

What is here: find the open pull request of a branch, open one (a draft unless told), read
one, mark one ready, replace its body, read its comments, reviews, resolved threads and
checks, post a comment, a reply or a review, list the signed-in account's open ones and the
ones that wait on its review, and ask the repository its default branch, whether a branch
is protected and what the account may do. What is NOT here, on purpose: merging, closing,
deleting a branch, and anything that pushes. A merge is the user's own, on GitHub.

**GitHub's words, in the kit's.** General comments, line comments and reviews are numbered
apart, so each comes back with its kind. A line comment's `parent` is the comment it
answers (`in_reply_to_id`), and a reply to it goes under its thread's first comment. An
app's comment (a `Bot` account, or a name ending `[bot]`) is a bot's. Which threads are
resolved is GitHub's GraphQL answer, read to the end (`resolved`). The head's checks are
its check runs and commit statuses (`statusCheckRollup`), read with the pull request itself
when the kit asks for a sight.
"""

import json
import re
from urllib.parse import quote

import gh_cli
from gh_cli import GithubError
from keel.packkit import VERSION
from keel.packkit.errors import OutsideChange
from keel.packkit.layer import GENERAL, LINES, PARTS, RESOLVED, REVIEWS, HostConfig, Repo, fold_checks

KIT = VERSION
DOMAIN = gh_cli.HOST
BASE = f"https://{DOMAIN}"
URL = "https://github.com/{slug}/pull/{number}"
STATES = {"OPEN": "open", "MERGED": "merged", "CLOSED": "declined"}
UNKNOWN = "unknown"
# `isCrossRepository` is what tells a pull request of the repository's own branch from one
# of a fork's: GitHub's own answer, which holds after a rename or a transfer, where a
# comparison of names with the clone's address would not.
FIELDS = "number,url,isDraft,title,state,headRefOid,headRefName,baseRefName,isCrossRepository"
FIND_MAX = "100"
SIGHT_FIELDS = FIELDS + ",author,statusCheckRollup"
MINE_FIELDS = "number,title,headRefName,isDraft,updatedAt,url"
MINE_MAX = "100"
SEARCH = "review-requested:@me"
LIST_FIELDS = ("number,title,body,author,createdAt,updatedAt,url,headRefName,headRefOid,"
               "baseRefName,isCrossRepository,isDraft")
LIST_MAX = "100"
NUMBER = re.compile(r"/pull/(\d+)\b")
# Which review threads are resolved, and the comments in each: the REST listings do not say.
# Both listings are paged to the end (`resolved`).
PAGE = "pageInfo{hasNextPage endCursor}"
THREADS = ("query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,"
           "name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$after){nodes{id "
           f"isResolved comments(first:100){{nodes{{databaseId}} {PAGE}}}}} {PAGE}}}}}}}}}")
THREAD = ("query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread{"
          f"comments(first:100,after:$after){{nodes{{databaseId}} {PAGE}}}}}}}}}")
PAGES_MAX = 30          # 3,000 threads, or 3,000 comments in one: past that it is refused
FAILED = ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE")
WAITING = ("PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED")
REVIEW_STATES = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested", "PENDING": "pending"}
EVENTS = {"approve": "APPROVE", "changes": "REQUEST_CHANGES"}
MAY_PUSH = ("WRITE", "MAINTAIN", "ADMIN")
# GitHub's answer when an inline comment's line is not in the change: the whole review is
# refused, so the kit posts it again with every finding in its body instead.
OUTSIDE_DIFF = re.compile(r"HTTP 422|Unprocessable|must be part of the diff|could not be resolved", re.I)


# ----- addresses, asked of nobody -----

# `git@host:owner/repo.git`, `ssh://git@host/owner/repo.git`, `https://[user@]host/owner/repo[.git][/]`
ADDRESS = re.compile(r"^(?:[a-z+]+://)?(?:[^@/]+@)?(?P<host>[^:/]+)(?::\d+)?[:/]"
                     r"(?P<path>[^/]+/[^/]+?)(?:\.git)?/?$")


def slug_of(address: str) -> str | None:
    """`owner/repo` when the address is a github.com one, else None."""
    found = ADDRESS.match((address or "").strip())
    if not found or found["host"].lower() not in (DOMAIN, f"www.{DOMAIN}"):
        return None
    return found["path"]


def address(remote_url: str, clone=None) -> Repo | None:
    slug = slug_of(remote_url)
    return Repo(slug, BASE, clone) if slug else None


def where(slug) -> str:
    return f"{DOMAIN}/{slug}"


def url(slug, number: int) -> str:
    return URL.format(slug=slug, number=int(number))


SIGN_GIT_IN = " (git has no sign-in for GitHub here: run `gh auth setup-git` in a terminal, then Ship again)"
NO_ACCOUNT = ("gh could not say which account is signed in ({why}), so the replies already posted cannot "
              "be told from the rest: nothing was pushed and no reply was posted; try again")
REVIEW_READS = """\
`gh` is signed in as the person you work for. Use it only to READ: `gh pr view {pr}`,
`gh pr diff {pr}`, `gh pr checks {pr}`, a plain `gh api <path>`. Never comment on, review,
approve or merge the {change} by hand: Approve outcome posts what the user keeps."""

HOST = HostConfig(
    name="GitHub", on="on GitHub", address=address, pr_url=url,
    elsewhere=lambda found: f"its address is {found}, which is not on {DOMAIN}",
    pull_head_ref="refs/pull/{n}/head",
    say={"sign_git_in": SIGN_GIT_IN, "no_account": NO_ACCOUNT, "review_reads": REVIEW_READS},
    ready="gh_ready", guard="gh_fence")


# ----- one pull request -----

def shaped(found: dict, slug) -> dict:
    number = int(found["number"])
    return {"id": number, "url": found.get("url") or url(slug, number), "draft": bool(found.get("isDraft")),
            "title": found.get("title"), "state": STATES.get(str(found.get("state") or "").upper(), UNKNOWN),
            "head": found.get("headRefOid"), "branch": found.get("headRefName"),
            "base": found.get("baseRefName"), "own": found.get("isCrossRepository") is False}


def find_open(slug, branch: str) -> dict | None:
    """The OPEN pull request from this branch OF THIS REPOSITORY, or None. gh's `--head`
    matches a branch name in anyone's fork too, so every match is read and a fork's is
    passed over: a stranger's pull request is never taken for the card's."""
    found = gh_cli.read("pr", "list", "-R", where(slug), "--head", branch, "--state", "open",
                        "--json", FIELDS, "--limit", FIND_MAX) or []
    return next((one for one in (shaped(row, slug) for row in found) if one["own"]), None)


def get(slug, number: int, sight: bool = False) -> dict:
    """One pull request; for a sight, with its author and its head's checks, in one call."""
    found = gh_cli.read("pr", "view", str(int(number)), "-R", where(slug), "--json",
                        SIGHT_FIELDS if sight else FIELDS)
    seen = shaped(found, slug)
    if sight:
        seen.update(author=(found.get("author") or {}).get("login"), rollup=found.get("statusCheckRollup") or [])
    return seen


def open_pr(slug, title: str, branch: str, base: str, body: str, draft: bool = True, cwd=None) -> dict:
    """Open the pull request from `branch` into `base`, the body handed on stdin so its
    text is never an argument. gh prints the new pull request's address."""
    said = gh_cli.run("pr", "create", "-R", where(slug), "--head", branch, "--base", base,
                      "--title", title, "--body-file", "-", *(["--draft"] if draft else []),
                      stdin=body, cwd=cwd)
    found = NUMBER.findall(said)
    if not found:
        raise GithubError(f"gh pr create did not say which pull request it opened from {branch}")
    return get(slug, int(found[-1]))


def set_ready(slug, number: int) -> None:
    gh_cli.run("pr", "ready", str(int(number)), "-R", where(slug))


def set_body(slug, number: int, body: str) -> None:
    gh_cli.run("pr", "edit", str(int(number)), "-R", where(slug), "--body-file", "-", stdin=body)


# ----- what people said on it -----

def issue_comments(slug, number: int) -> list[dict]:
    """The general comments (the conversation under the pull request)."""
    return gh_cli.api(f"repos/{slug}/issues/{int(number)}/comments")


def review_comments(slug, number: int) -> list[dict]:
    """The comments on lines of the change, replies included."""
    return gh_cli.api(f"repos/{slug}/pulls/{int(number)}/comments")


def reviews(slug, number: int) -> list[dict]:
    """Every submitted review: who, its state, when, and the words it came with."""
    return gh_cli.api(f"repos/{slug}/pulls/{int(number)}/reviews")


def graphql(query: str, *fields: str, after: str | None = None) -> dict:
    more = ["-f", f"after={after}"] if after else []
    found = gh_cli.read("api", "graphql", "--hostname", DOMAIN, "-f", f"query={query}", *fields, *more)
    return found.get("data") or {} if isinstance(found, dict) else {}


def ids_of(comments: dict) -> tuple[set[int], str | None]:
    """A page of a thread's comments: their ids, and the cursor of the next page if any."""
    page = comments.get("pageInfo") or {}
    ids = {int(one["databaseId"]) for one in comments.get("nodes") or [] if one.get("databaseId")}
    return ids, (page.get("endCursor") if page.get("hasNextPage") else None)


def rest_of(thread: str, after: str, what: str) -> set[int]:
    """The comments of one thread past its first page."""
    ids = set()
    for _ in range(PAGES_MAX):
        node = graphql(THREAD, "-f", f"id={thread}", after=after).get("node") or {}
        found, after = ids_of(node.get("comments") or {})
        ids |= found
        if not after:
            return ids
    raise GithubError(f"{what} has a review thread with more comments than can be read")


def resolved(slug, number: int) -> set[int]:
    """The ids of every line comment in a thread someone marked resolved, read to the end:
    every page of threads, and every page of a resolved thread's comments. A listing that
    will not end is refused, never read as whole."""
    owner, name = str(slug).split("/", 1)
    what, ids, after = f"{slug}#{int(number)}", set(), None
    for _ in range(PAGES_MAX):
        data = graphql(THREADS, "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={int(number)}",
                       after=after)
        try:
            threads = data["repository"]["pullRequest"]["reviewThreads"]
        except (KeyError, TypeError):
            raise GithubError(f"gh could not say which threads of {what} are resolved") from None
        for thread in threads.get("nodes") or []:
            if not thread.get("isResolved"):
                continue
            found, more = ids_of(thread.get("comments") or {})
            ids |= found | (rest_of(thread["id"], more, what) if more else set())
        page = threads.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return ids
        after = page.get("endCursor")
    raise GithubError(f"{what} has more review threads than can be read, so which are resolved is not known")


def login(row: dict) -> str | None:
    return (row.get("user") or {}).get("login")


def is_bot(row: dict) -> bool:
    who = row.get("user") or {}
    return who.get("type") == "Bot" or str(who.get("login") or "").lower().endswith("[bot]")


def comment_of(row: dict, kind: str = "g") -> dict:
    return {"kind": kind, "id": int(row["id"]), "author": login(row), "bot": is_bot(row), "body": row.get("body") or "",
            "at": row.get("created_at"), "updated": row.get("updated_at") or row.get("created_at"),
            "path": None, "line": None, "parent": None, "reply_to": int(row["id"]), "resolved": False}


def line_of(row: dict, done: set[int]) -> dict:
    under = row.get("in_reply_to_id")
    return dict(comment_of(row, "l"), path=row.get("path"), line=row.get("line") or row.get("original_line"),
                parent=int(under) if under else None, reply_to=int(under or row["id"]),
                resolved=int(row["id"]) in done)


def review_of(row: dict) -> dict:
    state = str(row.get("state") or "").upper()
    return {"id": row.get("id"), "author": login(row), "bot": is_bot(row),
            "state": REVIEW_STATES.get(state, "commented"), "dismissed": state == "DISMISSED",
            "body": row.get("body") or "", "at": row.get("submitted_at"), "url": row.get("html_url"),
            "comments_count": row.get("comments_count")}


def said(slug, number: int, parts=PARTS) -> dict:
    """What was said on it, in the kit's shapes, reading only the `parts` asked for: the
    line comments (and which are resolved), the reviews, then the conversation."""
    out = {GENERAL: [], LINES: [], REVIEWS: []}
    if LINES in parts:
        rows = review_comments(slug, number)
        done = resolved(slug, number) if RESOLVED in parts and rows else set()
        out[LINES] = [line_of(row, done) for row in rows]
    if REVIEWS in parts:
        out[REVIEWS] = [review_of(row) for row in reviews(slug, number)]
    if GENERAL in parts:
        out[GENERAL] = [comment_of(row) for row in issue_comments(slug, number)]
    return out


def check_of(one: dict) -> dict:
    """One check run (`status`, `conclusion`) or commit status (`state`), in the kit's words."""
    status = str(one.get("status") or "").upper()
    if str(one.get("conclusion") or one.get("state") or "").upper() in FAILED:
        state = "failed"
    elif (status and status != "COMPLETED") or str(one.get("state") or "").upper() in WAITING:
        state = "running"
    else:
        state = "passed"
    return {"state": state, "name": one.get("name") or one.get("context"),
            "url": one.get("detailsUrl") or one.get("targetUrl"), "at": one.get("completedAt") or one.get("startedAt")}


def checks_of(rollup: list[dict]) -> dict:
    """The head commit's checks as one word (the kit's fold over GitHub's rollup)."""
    return fold_checks([check_of(one) for one in rollup])


def checks(slug, pr: dict) -> list[dict]:
    rollup = pr.get("rollup")
    if rollup is None:
        rollup = get(slug, pr["id"], sight=True)["rollup"]
    return [check_of(one) for one in rollup]


def comment(slug, number: int, text: str) -> None:
    """A general comment, as the signed-in account."""
    gh_cli.run("pr", "comment", str(int(number)), "-R", where(slug), "--body-file", "-", stdin=text)


def reply(slug, number: int, under: int, text: str) -> None:
    """A reply in the thread of line comment `under` (the thread's first comment)."""
    gh_cli.run("api", "--hostname", DOMAIN, "--method", "POST",
               f"repos/{slug}/pulls/{int(number)}/comments/{int(under)}/replies", "--input", "-",
               stdin=json.dumps({"body": text}))


def post_review(slug, number: int, body: str, verdict: str, comments: list[dict], head) -> dict:
    """ONE review through GitHub's pull request review API: the findings inline at their
    lines (`side: RIGHT`), the body, the verdict as its event and the head reviewed."""
    payload = {"body": body, "event": EVENTS.get(verdict, "COMMENT"),
               "comments": [{"path": one["path"], "line": int(one["line"]), "side": "RIGHT", "body": one["text"]}
                            for one in comments]}
    if head:
        payload["commit_id"] = head
    try:
        done = gh_cli.read("api", "--hostname", DOMAIN, "--method", "POST",
                           f"repos/{slug}/pulls/{int(number)}/reviews", "--input", "-",
                           stdin=json.dumps(payload)) or {}
    except GithubError as error:
        if OUTSIDE_DIFF.search(str(error)):
            raise OutsideChange(str(error)) from None
        raise
    return {"id": done.get("id"), "url": done.get("html_url"), "inline_count": len(comments)}


# ----- lists -----

def listed(row: dict, slug) -> dict:
    number = int(row["number"])
    return {"id": number, "url": row.get("url"), "draft": bool(row.get("isDraft")), "title": row.get("title"),
            "state": "open", "head": row.get("headRefOid"), "branch": row.get("headRefName"),
            "base": row.get("baseRefName"), "own": row.get("isCrossRepository") is False,
            "author": (row.get("author") or {}).get("login"), "updated": row.get("updatedAt"),
            "created": row.get("createdAt"), "body": row.get("body")}


def review_requests(slug) -> list[dict]:
    """Every OPEN pull request that asks the signed-in account for its review (gh's own
    search, `review-requested:@me`, which GitHub also answers for a team the account is on)."""
    found = gh_cli.read("pr", "list", "-R", where(slug), "--search", SEARCH, "--state", "open",
                        "--json", LIST_FIELDS, "--limit", LIST_MAX) or []
    return [listed(row, slug) for row in found]


def mine(slug) -> list[dict]:
    """The open pull requests the signed-in account wrote in one repository."""
    found = gh_cli.read("pr", "list", "-R", where(slug), "--author", "@me", "--state", "open",
                        "--json", MINE_FIELDS, "--limit", MINE_MAX) or []
    return [listed(row, slug) for row in found]


# ----- the repository's branches -----

def default_branch(slug, timeout: int = gh_cli.SECONDS) -> str:
    """The branch GitHub calls the repository's default; raises when it does not say, or
    does not say within `timeout` seconds."""
    found = gh_cli.read("repo", "view", where(slug), "--json", "defaultBranchRef", timeout=timeout)
    name = ((found or {}).get("defaultBranchRef") or {}).get("name")
    if not name:
        raise GithubError(f"gh repo view named no default branch for {slug}")
    return str(name)


def protected(slug, branch: str) -> bool:
    """Whether GitHub reports the branch protected. A branch it has never heard of (a card's
    new branch before its first push) is not; any other failure is raised, never read as no."""
    try:
        found = gh_cli.read("api", "--hostname", DOMAIN, f"repos/{slug}/branches/{quote(branch, safe='/')}")
    except gh_cli.GhNotFound:
        return False
    return bool((found or {}).get("protected"))


# ----- the account -----

def signed_in(slug=None, timeout: int = gh_cli.SECONDS) -> None:
    """Raises unless gh has a working sign-in for github.com."""
    gh_cli.run("auth", "status", "--hostname", DOMAIN, timeout=timeout)


def account(slug=None, timeout: int = gh_cli.SECONDS) -> str:
    """The signed-in account's name."""
    return gh_cli.run("api", "--hostname", DOMAIN, "user", "--jq", ".login", timeout=timeout).strip()


def visible(slug, timeout: int = gh_cli.SECONDS) -> dict:
    """The repository as the signed-in account sees it, `{nameWithOwner, viewerPermission}`;
    raises `GhNotFound` when GitHub says there is none it may see."""
    return gh_cli.read("repo", "view", where(slug), "--json", "nameWithOwner,viewerPermission",
                       timeout=timeout) or {}


def access(slug, timeout: int = gh_cli.SECONDS) -> str:
    """`push` when GitHub says the account's permission is write, maintain or admin, else `read`."""
    permission = str(visible(slug, timeout=timeout).get("viewerPermission") or "").upper()
    return "push" if permission in MAY_PUSH else "read"
