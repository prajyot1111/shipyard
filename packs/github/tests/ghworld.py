"""The GitHub pack's stand-in hook: a `gh` on PATH that answers from a `World` (the kit's
`keel/packkit/world.py`), as GitHub would, for the conformance suite.

`install(folder, world_file)` puts a `gh` in `folder` that loads the world from `GH_WORLD`,
answers one command in GitHub's own shapes and words, and saves the world again; every write
goes through the world's own operations, so it is recorded there. A command it does not know
is recorded as an `unknown` write and refused, so a layer that asks for something new fails
the suite instead of passing on a guess. So is a method it does not implement on any api path
(`--method` and `-X` are read on every one, a field or an input meaning POST as gh means it,
r1.F2), and a flag on `pr edit`, `pr ready` or `pr comment` past what the layer sends (r2.F6). A
flag's value written in its word (`--method=DELETE`, `-XDELETE`) is read as gh reads it. `ghfake.py`'s planned answers are for the
transport's own tests; this is the world the contract runs in.
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote

from keel.packkit.world import World, WorldError

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = """#!{python}
import sys
sys.path[:0] = [{tests!r}, {root!r}]
import ghworld
sys.exit(ghworld.main(sys.argv[1:]))
"""
STATES = {"open": "OPEN", "merged": "MERGED", "declined": "CLOSED"}
REVIEW_STATES = {"approved": "APPROVED", "changes_requested": "CHANGES_REQUESTED", "commented": "COMMENTED",
                 "pending": "PENDING"}
EVENTS = {"APPROVE": "approve", "REQUEST_CHANGES": "changes"}
SIGNED_OUT = "To get started with GitHub CLI, please run:  gh auth login\n"


class Refused(Exception):
    def __init__(self, said: str, code: int = 1):
        super().__init__(said)
        self.code = code


def install(folder: Path) -> Path:
    script = Path(folder) / "gh"
    script.write_text(SCRIPT.format(python=sys.executable, tests=str(Path(__file__).resolve().parent), root=str(ROOT)))
    script.chmod(0o755)
    return script


# ----- GitHub's shapes -----

def user(name: str | None, bot: bool = False) -> dict | None:
    return {"login": name, "type": "Bot" if bot else "User"} if name else None


def check(one: dict) -> dict:
    done = {"failed": ("COMPLETED", "FAILURE"), "running": ("IN_PROGRESS", ""), "passed": ("COMPLETED", "SUCCESS")}
    status, conclusion = done[one["state"]]
    return {"__typename": "CheckRun", "name": one["name"], "status": status, "conclusion": conclusion,
            "detailsUrl": one["url"], "completedAt": one["at"]}


def pull(name: str, one: dict) -> dict:
    return {"number": one["id"], "url": f"https://github.com/{name}/pull/{one['id']}", "isDraft": one["draft"],
            "title": one["title"], "state": STATES.get(one["state"], "LOCKED_AWAY"), "headRefOid": one["head"],
            "headRefName": one["branch"], "baseRefName": one["base"], "isCrossRepository": not one["own"],
            "author": {"login": one["author"]}, "body": one["body"], "createdAt": one["created"],
            "updatedAt": one["updated"], "statusCheckRollup": [check(c) for c in one["checks"]]}


def said(one: dict, line: bool = False) -> dict:
    row = {"id": one["id"], "user": user(one["author"], one["bot"]), "body": one["body"], "created_at": one["at"],
           "updated_at": one["updated"]}
    if line:
        row.update(path=one["path"], line=one["line"], original_line=one["line"], in_reply_to_id=one["parent"])
    return row


def review(name: str, number: int, one: dict) -> dict:
    return {"id": one["id"], "user": user(one["author"], one["bot"]), "body": one["body"],
            "state": "DISMISSED" if one["dismissed"] else REVIEW_STATES[one["state"]], "submitted_at": one["at"],
            "html_url": f"https://github.com/{name}/pull/{number}#pullrequestreview-{one['id']}"}


def threads(world: World, change: dict) -> dict:
    found = {}
    for one in change["lines"]:
        found.setdefault(world.root(change, one["id"])["id"], []).append(one["id"])
    nodes = [{"id": f"T{root}", "isResolved": bool(world.root(change, root)["resolved"]),
              "comments": {"nodes": [{"databaseId": one} for one in ids],
                           "pageInfo": {"hasNextPage": False, "endCursor": None}}} for root, ids in found.items()]
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {
        "nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}


# ----- reading a command -----

VALUED = ("-R", "--head", "--base", "--title", "--body-file", "--state", "--json", "--limit", "--author",
          "--search", "--hostname", "--method", "-X", "--input", "--jq", "-f", "-F")


def split(word: str) -> tuple[str, str | None]:
    """A flag written with its value in one word, as gh reads it (r2.F6): `--method=DELETE`
    and `-XDELETE` are `--method DELETE` and `-X DELETE`."""
    if word.startswith("--") and "=" in word:
        name, _, value = word.partition("=")
        return name, value
    if not word.startswith("--") and word[:2] in VALUED and len(word) > 2:
        return word[:2], word[2:]
    return word, None


def flags(argv: list[str]) -> tuple[dict, list[str]]:
    """`--name value` pairs (`-R`, `-f`, `-F` too, repeatable ones as lists) and the bare words."""
    named, bare, at = {}, [], 0
    while at < len(argv):
        word, joined = split(argv[at]) if argv[at].startswith("-") else (argv[at], None)
        if joined is not None:
            named.setdefault(word, []).append(joined)
            at += 1
        elif word in VALUED and at + 1 < len(argv):
            named.setdefault(word, []).append(argv[at + 1])
            at += 2
        elif word.startswith("-"):
            named.setdefault(word, []).append("")
            at += 1
        else:
            bare.append(word)
            at += 1
    return {key: values[-1] if key not in ("-f", "-F") else values for key, values in named.items()}, bare


def repo_of(named: dict, bare: list[str]) -> str:
    where = named.get("-R") or next((word for word in bare if word.startswith("github.com/")), "")
    return where.removeprefix("github.com/")


def pr(world: World, verb: str, named: dict, bare: list[str], stdin: str):
    name = repo_of(named, bare)
    number = next((int(word) for word in bare if word.isdigit()), None)
    if verb == "list":
        if named.get("--author") == "@me":
            rows = world.mine(name)
        elif named.get("--search") == "review-requested:@me":
            rows = world.review_requests(name)
        else:
            rows = world.find_open(name, named.get("--head", ""))
        return [pull(name, one) for one in rows]
    if verb == "view":
        return pull(name, world.change(name, number))
    if verb == "create":
        made = world.open_pr(name, named["--title"], named["--head"], named["--base"], stdin, "--draft" in named)
        return f"https://github.com/{name}/pull/{made['id']}\n"
    if verb == "ready" and set(named) <= {"-R"}:               # `--undo` is no ready (r2.F6)
        return world.set_ready(name, number) or ""
    if verb == "edit" and set(named) <= {"-R", "--body-file"}:
        return world.set_body(name, number, stdin) or ""
    if verb == "comment" and set(named) <= {"-R", "--body-file"}:    # `--delete-last`, `--edit-last`
        world.comment(name, number, stdin)
        return ""
    raise KeyError(verb)


def method_of(named: dict) -> str:
    """The method gh sends: the one written, else POST with a field or an input, else GET."""
    written = named.get("--method") or named.get("-X")
    sends = any(key in named for key in ("-f", "-F", "--input"))
    return (written or ("POST" if sends else "GET")).upper()


def api(world: World, named: dict, bare: list[str], stdin: str):
    path = bare[0] if bare else ""
    method = method_of(named)
    if path == "user" and method == "GET":
        return world.account() + "\n"
    if path == "graphql" and method == "POST" and "mutation" not in " ".join(named.get("-f", [])):
        fields = dict(one.split("=", 1) for one in named.get("-f", []) + named.get("-F", []) if "=" in one)
        name = f"{fields['owner']}/{fields['name']}"
        return threads(world, world.change(name, int(fields["number"])))
    parts = path.split("/")
    name = "/".join(parts[1:3])
    if method not in ("GET", "POST"):
        raise KeyError(method)
    if parts[3:4] == ["branches"] and method == "GET":
        if world.protected(name, unquote("/".join(parts[4:]))):
            return {"name": parts[4], "protected": True}
        raise Refused("gh: Not Found (HTTP 404)\n")
    number = int(parts[4])
    change = world.change(name, number)
    if parts[3] == "issues" and parts[5:] == ["comments"] and method == "GET":
        return [said(one) for one in change["general"]]
    if parts[5:] == ["comments"] and method == "GET":
        return [said(one, line=True) for one in change["lines"]]
    if parts[5:6] == ["comments"] and parts[7:] == ["replies"] and method == "POST":
        world.reply(name, number, int(parts[6]), json.loads(stdin)["body"])
        return {}
    if parts[5:] == ["reviews"] and method == "POST":
        sent = json.loads(stdin)
        comments = [{"path": one["path"], "line": one["line"], "text": one["body"]} for one in sent["comments"]]
        try:
            made = world.post_review(name, number, sent["body"], EVENTS.get(sent["event"], "comment"), comments,
                                     sent.get("commit_id"))
        except WorldError:
            raise Refused("gh: Unprocessable Entity (HTTP 422)\n") from None
        return {"id": made["id"], "html_url": f"https://github.com/{name}/pull/{number}#pullrequestreview-{made['id']}"}
    if parts[5:] == ["reviews"] and method == "GET":
        return [review(name, number, one) for one in change["reviews"]]
    raise KeyError(path)


def repo(world: World, named: dict, bare: list[str]):
    name = repo_of(named, bare)
    if named.get("--json") == "defaultBranchRef":
        return {"defaultBranchRef": {"name": world.default_branch(name)}}
    return {"nameWithOwner": name, "viewerPermission": "WRITE" if world.access(name) == "push" else "READ"}


def answer(world: World, argv: list[str], stdin: str):
    named, bare = flags(argv)
    group, rest = (bare[0], bare[1:]) if bare else ("", [])
    world.check_in()
    if group == "auth" and rest[:1] == ["status"]:
        return "Logged in to github.com\n"
    if group == "pr" and rest:
        return pr(world, rest[0], named, rest[1:], stdin)
    if group == "api":
        return api(world, named, rest, stdin)
    if group == "repo" and rest[:1] == ["view"]:
        return repo(world, named, rest[1:])
    raise KeyError(group)


def careless(said: str) -> str:
    """A refusal as a careless host words it: the token it was sent, folded into the error
    (r1.F5), so the suite's no-token test can fail when a layer repeats a host's words."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return said.replace("\n", f" (sent with token {token})\n", 1) if token else said


def refusal(error: WorldError, argv: list[str]) -> Refused:
    if error.kind == "signed_out":
        return Refused(careless(SIGNED_OUT), 4)
    if error.kind == "not_found":
        what = "Repository with the name" if "repository" in str(error) else "PullRequest with the number of"
        return Refused(careless(f"GraphQL: Could not resolve to a {what} {argv[-1]}. (repository)\n"))
    return Refused(careless("gh: Server Error (HTTP 502)\n"))


def main(argv: list[str]) -> int:
    path = os.environ["GH_WORLD"]
    world = World.load(path)
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    try:
        out = answer(world, argv, stdin)
    except WorldError as error:
        world.save(path)
        failed = refusal(error, argv)
        sys.stderr.write(str(failed))
        return failed.code
    except Refused as refused:
        world.save(path)
        sys.stderr.write(str(refused))
        return refused.code
    except (KeyError, IndexError, ValueError):
        world.wrote("unknown", argv=argv)
        world.save(path)
        sys.stderr.write("gh stand-in: no answer for " + " ".join(argv) + "\n")
        return 64
    world.save(path)
    sys.stdout.write(out if isinstance(out, str) else json.dumps(out))
    return 0
