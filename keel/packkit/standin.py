"""The reference host layer: the contract (`layer.py`) made runnable over a `World`.

It is a layer like any pack's, over a world held in this process (`use(world)`), with a
host of its own (`HOST`: `https://standin.example/<owner>/<repo>`). The kit's own tests run
the conformance suite against it, which is what shows the contract can be met as written,
and `keel new pack --kit` starts a pack's stand-in hook from it. A pack's real layer is held
to the same suite through its own hook, which serves the same world as its host would.

A world's refusals become the kit's errors: signed out, not found, a review line outside the
change, and anything else as a plain `HostError`.
"""

import copy

from keel.packkit import VERSION
from keel.packkit.errors import HostError, NotFound, OutsideChange, SignedOut
from keel.packkit.layer import GENERAL, LINES, PARTS, RESOLVED, REVIEWS, HostConfig, Repo
from keel.packkit.world import World, WorldError

KIT = VERSION
BASE = "https://standin.example"
_world: World | None = None


def use(world: World) -> World:
    global _world
    _world = world
    return world


def address(remote_url: str, clone=None) -> Repo | None:
    url = (remote_url or "").strip().rstrip("/")
    if not url.startswith(BASE + "/"):
        return None
    parts = url[len(BASE) + 1:].removesuffix(".git").split("/")
    return Repo("/".join(parts), BASE, clone) if len(parts) == 2 and all(parts) else None


def pr_url(repo, number: int) -> str:
    return f"{BASE}/{repo}/changes/{int(number)}"


HOST = HostConfig(name="the stand-in", on="on the stand-in", address=address, pr_url=pr_url,
                  elsewhere=lambda found: f"its address is {found}, which is not on the stand-in")
ERRORS = {"signed_out": SignedOut, "not_found": NotFound, "outside": OutsideChange}


def ask(how, *args):
    """One world operation, its refusal said as the kit's error."""
    if _world is None:
        raise HostError("the stand-in has no world: call standin.use(world) first")
    try:
        return how(_world, *args)
    except WorldError as error:
        failed = ERRORS.get(error.kind, HostError)(f"the stand-in refused: {error}")
        raise failed from None


def shaped(found: dict, repo) -> dict:
    return {"id": found["id"], "url": pr_url(repo, found["id"]), "draft": found["draft"], "title": found["title"],
            "state": found["state"] if found["state"] in ("open", "merged", "declined") else "unknown",
            "head": found["head"], "branch": found["branch"], "base": found["base"], "own": found["own"],
            "author": found["author"], "updated": found["updated"]}


def find_open(repo, branch: str):
    return next((shaped(one, repo) for one in ask(World.find_open, str(repo), branch) if one["own"]), None)


def get(repo, number: int, sight: bool = False) -> dict:
    return shaped(ask(World.change, str(repo), number), repo)


def open_pr(repo, title: str, branch: str, base: str, body: str, draft: bool = True, cwd=None) -> dict:
    return shaped(ask(World.open_pr, str(repo), title, branch, base, body, draft), repo)


def set_ready(repo, number: int) -> None:
    ask(World.set_ready, str(repo), number)


def set_body(repo, number: int, body: str) -> None:
    ask(World.set_body, str(repo), number, body)


def said(repo, number: int, parts=PARTS) -> dict:
    found = ask(World.change, str(repo), number)
    out = {GENERAL: [], LINES: [], REVIEWS: []}
    if GENERAL in parts:
        out[GENERAL] = [dict(one, reply_to=one["id"]) for one in copy.deepcopy(found["general"])]
    if LINES in parts:
        roots = {one["id"]: one.get("parent") or one["id"] for one in found["lines"]}
        out[LINES] = [dict(one, reply_to=roots[one["id"]], resolved=bool(one["resolved"]) and RESOLVED in parts)
                      for one in copy.deepcopy(found["lines"])]
    if REVIEWS in parts:
        out[REVIEWS] = copy.deepcopy(found["reviews"])
    return out


def checks(repo, pr: dict) -> list[dict]:
    return copy.deepcopy(ask(World.change, str(repo), pr["id"])["checks"])


def comment(repo, number: int, text: str) -> None:
    ask(World.comment, str(repo), number, text)


def reply(repo, number: int, under: int, text: str) -> None:
    ask(World.reply, str(repo), number, under, text)


def post_review(repo, number: int, body: str, verdict: str, comments: list[dict], head) -> dict:
    return ask(World.post_review, str(repo), number, body, verdict, comments, head)


def review_requests(repo) -> list[dict]:
    return [dict(shaped(one, repo), body=one["body"], created=one["created"])
            for one in ask(World.review_requests, str(repo))]


def mine(repo) -> list[dict]:
    return [shaped(one, repo) for one in ask(World.mine, str(repo))]


def default_branch(repo, timeout: float = 30) -> str:
    return ask(World.default_branch, str(repo))


def protected(repo, branch: str) -> bool:
    return ask(World.protected, str(repo), branch)


def account(repo=None, timeout: float = 30) -> str:
    return ask(World.account)


def signed_in(repo=None, timeout: float = 30) -> None:
    ask(World.account)


def access(repo, timeout: float = 30) -> str:
    return ask(World.access, str(repo))
