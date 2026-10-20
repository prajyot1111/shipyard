"""A fake code host as plain data: the world a pack's conformance suite runs its layer in.

A `World` is one JSON-ready dict: the signed-in account, whether it is signed in, and each
repository (`owner/repo`) with its default branch, its protected branches, what the account
may do there, and its changes. A change holds what the kit reads (`layer.py` has the shapes)
and the lines it touches (`changed`), plus what was said on it, kept in the kit's own shapes.
Every write any host stand-in makes goes through one of its operations and is recorded in
`writes`, so a suite can say what was written, and that nothing else was.

The world is the same whichever host it stands in for. The kit's own stand-in (`standin.py`)
answers from it directly; a pack's stand-in hook serves it as its host would (the GitHub
pack's as a `gh` on PATH, the Gitea pack's as an HTTP API on 127.0.0.1), saving and loading
it with `save` and `load` when it runs in another process. It never holds a real credential:
`SECRET` is a marker the suites put where a token would be, and look for everywhere.

Standard library only.
"""

import json
from pathlib import Path

SECRET = "kit-735NotARealTokenOnlyAMarker0000"
WRITES = ("open_pr", "set_ready", "set_body", "comment", "reply", "post_review")
AT = "2026-10-01T10:00:00Z"


class WorldError(Exception):
    """What a host would refuse: `kind` is `signed_out`, `not_found`, `outside` or `error`."""

    def __init__(self, kind: str, said: str):
        super().__init__(said)
        self.kind = kind


class World:
    """The data, and the host's operations on it."""

    def __init__(self, data: dict | None = None):
        self.data = data or {"account": "me", "signed_in": True, "repos": {}, "writes": [], "fail": {},
                             "next": {"change": 11, "g": 100, "l": 200, "r": 300, "check": 400}}

    # ----- keeping it -----

    @classmethod
    def load(cls, path) -> "World":
        return cls(json.loads(Path(path).read_text()))

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.data, indent=1, sort_keys=True))

    @property
    def writes(self) -> list[dict]:
        return self.data["writes"]

    def next(self, kind: str) -> int:
        self.data["next"][kind] += 1
        return self.data["next"][kind]

    def wrote(self, op: str, **what) -> None:
        self.data["writes"].append({"op": op, **what})

    # ----- seeding it -----

    def repo(self, name: str, default: str = "main", access: str = "push") -> dict:
        """The repository `owner/repo`, made when it is not there. `access` is `push`, `read`
        or `none` (the account may not see it)."""
        return self.data["repos"].setdefault(name, {"default": default, "protected": [], "access": access,
                                                    "changes": {}})

    def change(self, name: str, number: int) -> dict:
        self.check_in()
        found = self.data["repos"].get(name)
        if found is None or found["access"] == "none":
            raise WorldError("not_found", f"there is no repository {name}")
        if str(int(number)) not in found["changes"]:
            raise WorldError("not_found", f"there is no change #{int(number)} in {name}")
        return found["changes"][str(int(number))]

    def add_change(self, name: str, branch: str, base: str = "main", title: str = "A change", author: str = "me",
                   own: bool = True, draft: bool = False, state: str = "open", head: str = "abc123",
                   changed: dict | None = None, requested: list | None = None, body: str = "") -> int:
        number = self.next("change")
        self.repo(name)["changes"][str(number)] = {
            "id": number, "title": title, "body": body, "branch": branch, "base": base, "head": head,
            "draft": draft, "state": state, "own": own, "author": author, "created": AT, "updated": AT,
            "changed": changed if changed is not None else {"loader.py": list(range(1, 21))},
            "general": [], "lines": [], "reviews": [], "checks": [], "requested": list(requested or [])}
        return number

    def say(self, name: str, number: int, author: str, body: str, path: str | None = None, line: int | None = None,
            under: int | None = None, bot: bool = False, resolved: bool = False, at: str = AT) -> int:
        """Someone's comment: on a line when `path` and `line` are given, else a general one."""
        found = self.data["repos"][name]["changes"][str(int(number))]
        kind = "l" if path else "g"
        one = {"kind": kind, "id": self.next(kind), "author": author, "bot": bot, "body": body, "at": at,
               "updated": at, "path": path, "line": line, "parent": under, "resolved": resolved}
        found["lines" if path else "general"].append(one)
        return one["id"]

    def add_review(self, name: str, number: int, author: str, state: str, body: str = "", dismissed: bool = False,
                   at: str = AT) -> int:
        found = self.data["repos"][name]["changes"][str(int(number))]
        one = {"id": self.next("r"), "author": author, "bot": False, "state": state, "dismissed": dismissed,
               "body": body, "at": at, "comments_count": 0}
        found["reviews"].append(one)
        return one["id"]

    def add_check(self, name: str, number: int, state: str, check: str = "tests") -> None:
        found = self.data["repos"][name]["changes"][str(int(number))]
        found["checks"].append({"state": state, "name": check, "url": f"https://ci.example/{self.next('check')}",
                                "at": AT})

    # ----- the host's operations -----

    def check_in(self) -> None:
        failing = self.data["fail"].get("all")
        if failing:
            raise WorldError(failing, f"the host failed: {failing}")
        if not self.data["signed_in"]:
            raise WorldError("signed_out", "no sign-in the host accepts")

    def visible(self, name: str) -> dict:
        self.check_in()
        found = self.data["repos"].get(name)
        if found is None or found["access"] == "none":
            raise WorldError("not_found", f"there is no repository {name}")
        return found

    def find_open(self, name: str, branch: str) -> list[dict]:
        """Every open change from a branch of this name, a fork's included."""
        return [one for one in self.visible(name)["changes"].values() if one["state"] == "open"
                and one["branch"] == branch]

    def open_pr(self, name: str, title: str, branch: str, base: str, body: str, draft: bool) -> dict:
        self.visible(name)
        number = self.add_change(name, branch, base, title, self.data["account"], True, draft, body=body)
        self.wrote("open_pr", repo=name, n=number, branch=branch, base=base, draft=draft)
        return self.change(name, number)

    def set_ready(self, name: str, number: int) -> None:
        self.change(name, number)["draft"] = False
        self.wrote("set_ready", repo=name, n=int(number))

    def set_body(self, name: str, number: int, body: str) -> None:
        self.change(name, number)["body"] = body
        self.wrote("set_body", repo=name, n=int(number))

    def comment(self, name: str, number: int, text: str) -> int:
        self.change(name, number)
        made = self.say(name, number, self.data["account"], text)
        self.wrote("comment", repo=name, n=int(number), id=made)
        return made

    def root(self, found: dict, under: int) -> dict:
        lines = {one["id"]: one for one in found["lines"]}
        if int(under) not in lines:
            raise WorldError("not_found", f"there is no line comment {under}")
        one = lines[int(under)]
        while one.get("parent") in lines:
            one = lines[one["parent"]]
        return one

    def reply(self, name: str, number: int, under: int, text: str) -> int:
        """A reply in the conversation of line comment `under`: on its line, under its first."""
        found = self.change(name, number)
        first = self.root(found, under)
        made = self.say(name, number, self.data["account"], text, first["path"], first["line"], first["id"])
        self.wrote("reply", repo=name, n=int(number), under=int(under), id=made)
        return made

    def post_review(self, name: str, number: int, body: str, verdict: str, comments: list[dict], head,
                    any_line: bool = False) -> dict:
        """ONE review. A host that refuses a finding on a line the change does not touch
        (`changed`) refuses the whole review, as GitHub does; one that takes any line
        (`any_line`, as Gitea does) posts it where it was put, so the layer must look first."""
        found = self.change(name, number)
        for one in comments:
            if not any_line and int(one["line"]) not in (found["changed"].get(one["path"]) or []):
                raise WorldError("outside", f"{one['path']}:{one['line']} is not part of the change")
        state = {"approve": "approved", "changes": "changes_requested"}.get(verdict, "commented")
        made = self.add_review(name, number, self.data["account"], state, body)
        found["reviews"][-1]["comments_count"] = len(comments)
        for one in comments:
            self.say(name, number, self.data["account"], one["text"], one["path"], int(one["line"]))
        self.wrote("post_review", repo=name, n=int(number), id=made, verdict=verdict, inline=len(comments),
                   head=head)
        return {"id": made, "url": f"review-{made}", "inline_count": len(comments)}

    def review_requests(self, name: str) -> list[dict]:
        me = self.data["account"]
        return [one for one in self.visible(name)["changes"].values() if one["state"] == "open"
                and me in one["requested"] and one["author"] != me]

    def mine(self, name: str) -> list[dict]:
        me = self.data["account"]
        return [one for one in self.visible(name)["changes"].values() if one["state"] == "open"
                and one["author"] == me and one["own"]]

    def default_branch(self, name: str) -> str:
        return self.visible(name)["default"]

    def protected(self, name: str, branch: str) -> bool:
        return branch in self.visible(name)["protected"]

    def account(self) -> str:
        self.check_in()
        return self.data["account"]

    def access(self, name: str) -> str:
        return self.visible(name)["access"]
