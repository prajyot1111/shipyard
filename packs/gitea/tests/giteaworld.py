"""The Gitea pack's stand-in hook: an HTTP server on 127.0.0.1 that answers Gitea's API
(`/api/v1`) from a `World` (the kit's `keel/packkit/world.py`), for the conformance suite.

`Served(folder)` starts the server and writes a git credential helper into `folder` that
hands git the user name `me` and the token kept in `token` there; the server accepts only
that token, by HTTP Basic, as a Gitea accepts a token in place of a password. The world is
loaded from `world.json` there for each request and saved after it, so the suite and the
verbs (other processes) see one world. Every write goes through the world's own operations,
so it is recorded there; a request it does not know is recorded as an `unknown` write and
refused (HTTP 501), so a layer that asks for something new fails the suite instead of
passing on a guess.

Gitea's ways, as the stand-in serves them: a draft is a title starting `WIP: ` (the world
keeps the flag and the bare title); every method and every edit field it does not implement
(a DELETE, a PUT, a pull request's `state`, a title that is not the draft mark coming off, a
field of a new pull request past head, base, title and body) is an `unknown` write, so a layer that closes,
deletes or merges fails the write budget (r1.F2); a comment on a line belongs to a review, so one the
world holds outside any review (seeded, or a reply) is served under a review of its own
that only commented, as Gitea serves a single comment; and a resolved line comment has a
`resolver`. `fail` in the world's data stands in for Gitea's refusals: `scope` (a token
not allowed that scope, HTTP 403 in Gitea's words) and `replies` (a Gitea with no replies
call: the status it is set to, 404 or 405). Like Gitea, it posts a review comment on any line,
one the change does not touch included, and serves the change's diff (`pulls/<n>.diff`) from
the world's `changed` lines.
"""

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from keel.packkit.world import World, WorldError

PREFIX = "/api/v1/"
OWN_REPO, FORK = 1, 2
SYNTHETIC = 900000            # a lone line comment's own review: this plus the comment's id
STATES = {"approved": "APPROVED", "changes_requested": "REQUEST_CHANGES", "commented": "COMMENT",
          "pending": "PENDING"}
EVENTS = {"APPROVED": "approve", "REQUEST_CHANGES": "changes"}
STATUS = {"passed": "success", "running": "pending", "failed": "failure"}
REFUSALS = {"signed_out": 401, "not_found": 404, "outside": 422}
CARELESS = (403, 404, 422)          # the statuses whose words fold in the token sent (r2.F4)
MARK = re.compile(r"^\s*(?:WIP:|\[WIP\])\s*", re.I)
HELPER = """#!/bin/sh
test "$1" = get || exit 0
while read -r line; do test -n "$line" || break; done
read -r token < {token}
printf 'username=me\\npassword=%s\\n' "$token"
"""


class Refused(Exception):
    def __init__(self, status: int, said: str):
        super().__init__(said)
        self.status = status


# ----- Gitea's shapes -----

def user(name: str | None) -> dict | None:
    return {"login": name, "id": 7} if name else None


def pull(base: str, name: str, one: dict) -> dict:
    merged = one["state"] == "merged"
    state = {"open": "open", "merged": "closed", "declined": "closed"}.get(one["state"], "weird")
    return {"number": one["id"], "html_url": f"{base}/{name}/pulls/{one['id']}", "draft": one["draft"],
            "title": ("WIP: " if one["draft"] else "") + one["title"], "state": state, "merged": merged,
            "head": {"ref": one["branch"], "sha": one["head"], "repo_id": OWN_REPO if one["own"] else FORK},
            "base": {"ref": one["base"], "repo_id": OWN_REPO}, "user": user(one["author"]), "body": one["body"],
            "created_at": one["created"], "updated_at": one["updated"],
            "requested_reviewers": [user(who) for who in one["requested"]]}


def comment(one: dict) -> dict:
    row = {"id": one["id"], "user": user(one["author"]), "body": one["body"], "created_at": one["at"],
           "updated_at": one["updated"]}
    if one["path"]:
        row.update(path=one["path"], position=one["line"], original_position=one["line"],
                   resolver=user("ana") if one["resolved"] else None,
                   pull_request_review_id=one.get("review") or SYNTHETIC + one["id"])
    return row


def review(base: str, name: str, number: int, one: dict, count: int) -> dict:
    return {"id": one["id"], "user": user(one["author"]), "body": one["body"], "state": STATES[one["state"]],
            "dismissed": one["dismissed"], "submitted_at": one["at"], "comments_count": count,
            "html_url": f"{base}/{name}/pulls/{number}#issuecomment-{one['id']}"}


def lone(one: dict) -> dict:
    """The review Gitea serves a single line comment under."""
    return {"id": SYNTHETIC + one["id"], "author": one["author"], "body": "", "state": "commented",
            "dismissed": False, "at": one["at"]}


def reviews(base: str, name: str, number: int, change: dict) -> list[dict]:
    counts = {}
    for one in change["lines"]:
        counts[one.get("review") or SYNTHETIC + one["id"]] = counts.get(one.get("review") or SYNTHETIC + one["id"], 0) + 1
    rows = [*change["reviews"], *(lone(one) for one in change["lines"] if not one.get("review"))]
    return [review(base, name, number, one, counts.get(one["id"], 0)) for one in rows]


def under_review(change: dict, review_id: int) -> list[dict]:
    return [comment(one) for one in change["lines"] if (one.get("review") or SYNTHETIC + one["id"]) == review_id]


def statuses(world: World, name: str, sha: str) -> dict:
    found = [check for one in world.visible(name)["changes"].values() if one["head"] == sha for check in one["checks"]]
    rows = [{"status": STATUS[one["state"]], "context": one["name"], "target_url": one["url"], "updated_at": one["at"]}
            for one in found]
    return {"sha": sha, "state": "failure" if any(r["status"] == "failure" for r in rows) else "success",
            "statuses": rows}


def diff(change: dict) -> str:
    """The change's unified diff as Gitea serves `pulls/<n>.diff`: each run of the world's
    `changed` lines one hunk of added lines."""
    rows = []
    for path, lines in sorted(change["changed"].items()):
        rows += [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}"]
        runs = []
        for line in sorted(lines):
            if runs and line == runs[-1][-1] + 1:
                runs[-1].append(line)
            else:
                runs.append([line])
        for run in runs:
            rows.append(f"@@ -{run[0] - 1},0 +{run[0]},{len(run)} @@")
            rows += [f"+line {line}" for line in run]
    return "\n".join(rows) + "\n"


# ----- answering one request -----

class Request:
    def __init__(self, base: str, world: World, method: str, path: str, query: dict, body):
        self.base, self.world, self.method, self.query, self.body = base, world, method, query, body
        self.parts = [unquote(part) for part in path.split("/") if part]

    def answer(self):
        if self.parts == ["user"] and self.method == "GET":
            self.scoped("read:user")
            return 200, {"login": self.world.account(), "id": 7}
        if self.parts[:1] != ["repos"] or len(self.parts) < 3:
            raise KeyError(self.parts)
        self.name, rest = "/".join(self.parts[1:3]), self.parts[3:]
        return self.repo(rest)

    def scoped(self, needs: str) -> None:
        missing = self.world.data["fail"].get("scope")
        if missing == needs:
            raise Refused(403, f"token does not have at least one of required scope(s), required=[{needs}], "
                               f"token scope=write:repository")

    def repo(self, rest: list[str]):
        world, name = self.world, self.name
        if not rest and self.method == "GET":
            found = world.visible(name)
            return 200, {"full_name": name, "default_branch": found["default"],
                         "permissions": {"pull": True, "push": found["access"] == "push"}}
        if rest[0] == "branches" and self.method == "GET":
            branch = "/".join(rest[1:])
            if world.protected(name, branch):
                return 200, {"name": branch, "protected": True}
            raise Refused(404, "GetBranch")
        if rest[0] == "commits" and rest[2:] == ["status"] and self.method == "GET":
            return 200, statuses(world, name, rest[1])
        if rest[0] == "issues":
            return self.issues(rest[1:])
        if rest[0] == "pulls":
            return self.pulls(rest[1:])
        raise KeyError(rest)

    def issues(self, rest: list[str]):
        if rest == ["comments"] and self.method == "GET":
            self.scoped("read:issue")
            self.world.visible(self.name)
            return 200, []
        number = int(rest[0])
        change = self.world.change(self.name, number)
        if rest[1:] == ["comments"] and self.method == "GET":
            self.scoped("read:issue")
            return 200, [comment(one) for one in change["general"]]
        if rest[1:] == ["comments"] and self.method == "POST":
            self.scoped("write:issue")
            made = self.world.comment(self.name, number, self.body["body"])
            return 201, comment(next(one for one in change["general"] if one["id"] == made))
        raise KeyError(rest)

    def pulls(self, rest: list[str]):
        world, name = self.world, self.name
        if not rest and self.method == "GET":
            if int(self.query.get("page", ["1"])[0]) > 1:
                return 200, []
            wanted = self.query.get("state", ["open"])[0]
            return 200, [pull(self.base, name, one) for one in world.visible(name)["changes"].values()
                         if wanted == "all" or (one["state"] == "open") == (wanted == "open")]
        if not rest and self.method == "POST":
            if set(self.body) - {"head", "base", "title", "body"}:
                raise KeyError(sorted(self.body))       # an assignee, a label, a milestone (r2.F5)
            title = self.body["title"]
            made = world.open_pr(name, MARK.sub("", title, count=1), self.body["head"], self.body["base"],
                                 self.body.get("body") or "", bool(MARK.match(title)))
            return 201, pull(self.base, name, made)
        if rest[0].endswith(".diff") and rest[1:] == [] and self.method == "GET":
            return 200, diff(world.change(name, int(rest[0].removesuffix(".diff"))))
        number = int(rest[0])
        change = world.change(name, number)
        if rest[1:] == [] and self.method == "GET":
            return 200, pull(self.base, name, change)
        if rest[1:] == [] and self.method == "PATCH":
            return 201, self.edit(number, change)
        if rest[1:] == ["reviews"]:
            return self.review(number, change)
        if rest[1:2] == ["reviews"] and rest[3:] == ["comments"] and self.method == "GET":
            return 200, under_review(change, int(rest[2]))
        if rest[1:2] == ["comments"] and rest[3:] == ["replies"] and self.method == "POST":
            if world.data["fail"].get("replies"):          # 404, or 405 where the route is there but not the method
                raise Refused(int(world.data["fail"]["replies"]), "Not Found" if world.data["fail"]["replies"] == 404
                              else "Method Not Allowed")
            made = world.reply(name, number, int(rest[2]), self.body["body"])
            return 201, comment(next(one for one in change["lines"] if one["id"] == made))
        raise KeyError(rest)

    def edit(self, number: int, change: dict) -> dict:
        unknown = set(self.body) - {"title", "body"}
        if unknown:
            raise KeyError(sorted(unknown))             # a `state`, a base, an assignee: not the contract's
        if "title" in self.body:
            title = self.body["title"]
            if not change["draft"] or MARK.match(title) or title != change["title"]:
                raise KeyError("title")                 # only the mark coming off is the contract's (r2.F5)
            self.world.set_ready(self.name, number)
        if "body" in self.body:
            self.world.set_body(self.name, number, self.body["body"])
        return pull(self.base, self.name, change)

    def review(self, number: int, change: dict):
        if self.method == "GET":
            if int(self.query.get("page", ["1"])[0]) > 1:
                return 200, []
            return 200, reviews(self.base, self.name, number, change)
        if self.method != "POST":
            raise KeyError(self.method)
        sent = self.body
        comments = [{"path": one["path"], "line": one["new_position"], "text": one["body"]}
                    for one in sent.get("comments") or []]
        before = {one["id"] for one in change["lines"]}
        made = self.world.post_review(self.name, number, sent.get("body") or "", EVENTS.get(sent.get("event"), "comment"),
                                      comments, sent.get("commit_id"), any_line=True)
        for one in change["lines"]:
            if one["id"] not in before:
                one["review"] = made["id"]
        mine = next(one for one in change["reviews"] if one["id"] == made["id"])
        return 200, review(self.base, self.name, number, mine, len(comments))


def without_draft(payload):
    """A Gitea that sends no `draft` field (`fail.no_draft_field`): its title says it alone."""
    if isinstance(payload, list):
        return [without_draft(one) for one in payload]
    return {key: value for key, value in payload.items() if key != "draft"} if isinstance(payload, dict) else payload


# ----- the server -----

class Served:
    """The stand-in, serving the world in `folder/world.json` at `base` until `stop()`."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.world_file, self.token_file = self.folder / "world.json", self.folder / "token"
        self.token_file.write_text("standin-token\n")
        self.helper = self.folder / "credential-helper"
        self.helper.write_text(HELPER.format(token=self.token_file))
        self.helper.chmod(0o755)
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def git_config(self) -> list[tuple[str, str]]:
        """git's sign-in for the stand-in, and only it: the empty helper first empties the list."""
        return [("credential.helper", ""), ("credential.helper", str(self.helper))]

    def secret(self, marker: str) -> None:
        self.token_file.write_text(marker + "\n")

    def presented(self, header: str | None) -> str:
        """The password (or token) a request was sent with, "" for none."""
        if not (header or "").startswith("Basic "):
            return ""
        return base64.b64decode(header[6:]).decode().partition(":")[2]

    def signed(self, header: str | None) -> bool:
        return bool(self.presented(header)) and self.presented(header) == self.token_file.read_text().strip()

    def careless(self, status: int, said: str, header: str | None) -> dict:
        """An error as a careless host words it: a 403, 404 or 422 names the token it was sent
        (r2.F4), so the suite's no-token test can fail when a layer repeats a host's words."""
        token = self.presented(header)
        return {"message": f"{said} (sent with token {token})" if token and status in CARELESS else said}

    def handle(self, method: str, raw_path: str, header: str | None, body: bytes) -> tuple[int, object]:
        parts = urlsplit(raw_path)
        if not parts.path.startswith(PREFIX):
            return 404, {"message": "Not Found"}
        with self.lock:
            world = World.load(self.world_file)
            try:
                if not self.signed(header):
                    raise Refused(401, "user does not exist [uid: 0, name: ]")
                sent = json.loads(body) if body else {}
                found = Request(self.base, world, method, parts.path[len(PREFIX):], parse_qs(parts.query), sent)
                status, payload = found.answer()
                return status, without_draft(payload) if world.data["fail"].get("no_draft_field") else payload
            except WorldError as error:
                status = REFUSALS.get(error.kind, 500)
                return status, self.careless(status, "token is required" if status == 401 else str(error), header)
            except Refused as refused:
                return refused.status, self.careless(refused.status, str(refused), header)
            except (KeyError, IndexError, ValueError, TypeError):
                world.wrote("unknown", method=method, path=parts.path)
                return 501, {"message": f"the stand-in has no answer for {method} {parts.path}"}
            finally:
                world.save(self.world_file)


def handler(served: Served):
    class Handler(BaseHTTPRequestHandler):
        def respond(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            status, payload = served.handle(self.command, self.path, self.headers.get("Authorization"),
                                            self.rfile.read(length) if length else b"")
            plain = isinstance(payload, str)                # a diff is text, as Gitea sends it
            data = payload.encode() if plain else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain" if plain else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = respond

        def log_message(self, *args) -> None:
            """Quiet: the suite reads the world, not the log."""
    return Handler
