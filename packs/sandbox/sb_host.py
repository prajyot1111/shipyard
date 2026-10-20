"""The sandbox's code host: pull requests as JSON files under `<sandbox>/host/`.

One file per pull request, `host/<repo>/<number>.json`, written atomically:

    {"repo", "number", "title", "description", "author": {"id", "name"}, "branch", "base",
     "state": "open" | "merged" | "declined", "draft", "head", "reviewers": [ids],
     "reviews": [{"author", "state", "at"}], "comments": [{"id", "author", "at", "path",
     "line", "parent", "text", "bot"?, "resolved"?}], "ci": {"state", ...}, "created", "updated"}

A comment with `"bot": true` is an app's, and a thread's root with `"resolved": true` closes
that thread (`resolve`): `ship <id> poll` leaves both out, as the work adapter does.

An open pull request's head is read from the bare origin each time, so a push is seen at
once, the way a real host sees it. A link is `https://code.sandbox.test/<repo>/pull/<n>`:
`.test` is a reserved name that resolves nowhere.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from sb_card import ME, SandboxError, git, home, origin_path

URL = "https://code.sandbox.test/{repo}/pull/{number}"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def url(repo: str, number: int) -> str:
    return URL.format(repo=repo, number=int(number))


def root() -> Path:
    return home() / "host"


def path_of(repo: str, number: int) -> Path:
    return root() / repo / f"{int(number)}.json"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w") as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write("\n")
    os.replace(tmp, path)


def origin_head(repo: str, branch: str) -> str | None:
    found = git(origin_path(repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return found.stdout.strip() or None if found.returncode == 0 else None


def get(repo: str, number: int) -> dict:
    path = path_of(repo, number)
    if not path.is_file():
        raise SandboxError(f"{repo} has no pull request #{number}")
    pr = json.loads(path.read_text())
    if pr["state"] == "open":
        pr["head"] = origin_head(repo, pr["branch"]) or pr.get("head")
    pr["url"] = url(repo, pr["number"])
    return pr


def save(pr: dict) -> dict:
    pr = dict(pr, updated=now())
    pr.pop("url", None)
    write_json(path_of(pr["repo"], pr["number"]), pr)
    return get(pr["repo"], pr["number"])


def listed(repo: str) -> list[dict]:
    folder = root() / repo
    if not folder.is_dir():
        return []
    numbers = sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit())
    return [get(repo, number) for number in numbers]


def repos() -> list[str]:
    return sorted(p.name for p in root().iterdir() if p.is_dir()) if root().is_dir() else []


def open_prs(repo: str) -> list[dict]:
    return [pr for pr in listed(repo) if pr["state"] == "open"]


def find_open(repo: str, branch: str) -> dict | None:
    return next((pr for pr in open_prs(repo) if pr["branch"] == branch), None)


def next_number(repo: str) -> int:
    numbers = [pr["number"] for pr in listed(repo)]
    return max(numbers, default=0) + 1


def open_pr(repo: str, title: str, branch: str, base: str, description: str, draft: bool = True,
            author: dict | None = None, reviewers: list[str] | None = None, at: str | None = None) -> dict:
    head = origin_head(repo, branch)
    if head is None:
        raise SandboxError(f"branch {branch} is not on {repo}'s origin: push it first")
    stamp = at or now()
    pr = {"repo": repo, "number": next_number(repo), "title": title, "description": description,
          "author": author or ME, "branch": branch, "base": base, "state": "open", "draft": draft,
          "head": head, "reviewers": list(reviewers or []), "reviews": [], "comments": [],
          "ci": {"state": "passed"}, "created": stamp, "updated": stamp}
    write_json(path_of(repo, pr["number"]), pr)
    return get(repo, pr["number"])


def set_draft(repo: str, number: int, draft: bool) -> dict:
    pr = get(repo, number)
    return pr if pr["draft"] == draft else save(dict(pr, draft=draft))


def set_state(repo: str, number: int, state: str) -> dict:
    return save(dict(get(repo, number), state=state))


def comment(repo: str, number: int, text: str, path: str | None = None, line: int | None = None,
            parent: int | None = None, author: dict | None = None, bot: bool = False) -> dict:
    pr = get(repo, number)
    ids = [c["id"] for p in listed(repo) for c in p["comments"]]
    one = {"id": max(ids, default=100) + 1, "author": author or ME, "at": now(), "path": path,
           "line": int(line) if line else None, "parent": parent, "text": text}
    if bot:
        one["bot"] = True
    save(dict(pr, comments=pr["comments"] + [one]))
    return one


def edit(repo: str, number: int, comment_id: int, text: str) -> dict:
    """A reviewer changes what a comment says, as a real host keeps it: same id, new time."""
    pr = get(repo, number)
    comments = [dict(c, text=text, updated=now()) if c["id"] == int(comment_id) else c
                for c in pr["comments"]]
    return save(dict(pr, comments=comments))


def resolve(repo: str, number: int, comment_id: int) -> dict:
    """Mark a thread resolved, on its root comment, as a reviewer does on a real host."""
    pr = get(repo, number)
    comments = [dict(c, resolved=True) if c["id"] == int(comment_id) else c for c in pr["comments"]]
    return save(dict(pr, comments=comments))


def review(repo: str, number: int, state: str, author: dict | None = None) -> dict:
    """One reviewer's verdict: `approved` or `changes_requested`, the newest per reviewer."""
    who = author or ME
    pr = get(repo, number)
    kept = [r for r in pr["reviews"] if r["author"]["id"] != who["id"]]
    return save(dict(pr, reviews=kept + [{"author": who, "state": state, "at": now()}]))
