"""What the sandbox's code host says, in the engine's words: `ship` and `review`.

- `ship <id> poll`: the shipping card's pull request as a SIGHT (`keel/shipwatch.py` has
  the shape): state, draft, url, head, behind, the comments by anyone but its author (a
  bot's, and every comment of a resolved thread, left out), the reviews, the approvals, the
  checks; a card with one per repo as `{state, url, head, prs: [...]}`.
- `ship <id> diff`: each pull request's diff against its base, from the repo's clone.
- `ship <id> method`: how a house judges review (`sb_brief.METHOD`), printed by `sb_main`.
- `ship <id> down`: nothing to stop, the sandbox runs no containers.
- `ship <id> reap`: the done card's worktrees removed, one with changes kept.
- `ship mine`: his open pull requests, each with the cards it matches by branch, else story.
- `review scan`: every open pull request where he is a reviewer, not the author, and has not
  approved; `review <id> poll`, `review branches`, `review story`.
Reads only, but for `reap`.
"""

import sb_host
import sb_tracker
from sb_card import (ME, SandboxError, base_of, git, home, is_research, is_review, is_tracking, option,
                     origin_path, prs_of, repo_path, repos_of, story_of, worktree_of)
from sb_cut import tree_path

DIFF_MAX = 80000


# ----- ship -----

def entries_of(card: dict) -> list[dict]:
    entries = prs_of(card)
    if not entries:
        raise SandboxError(f"card {card['id']} has no pull request (options.pr or options.prs) to watch")
    return entries


def behind(card: dict, entry: dict) -> int | None:
    repo = repo_path(entry["repo"])
    git(repo, "fetch", "--quiet", "origin")
    counted = git(repo, "rev-list", "--count", f"origin/{entry['branch']}..origin/{base_of(card)}")
    out = counted.stdout.strip()
    return int(out) if counted.returncode == 0 and out.isdigit() else None


def resolved_ids(comments: list[dict]) -> set:
    """Every comment whose parent chain reaches a root marked resolved."""
    parent = {c["id"]: c.get("parent") for c in comments}
    roots = {c["id"] for c in comments if c.get("resolved")}
    out = set()
    for one in parent:
        seen, at = set(), one
        while at is not None and at not in seen and at not in roots:
            seen.add(at)
            at = parent.get(at)
        if at in roots:
            out.add(one)
    return out


def comments_of(pr: dict) -> list[dict]:
    author, resolved = pr["author"]["id"], resolved_ids(pr["comments"])
    return [{"id": c["id"], "author": c["author"]["name"], "at": c["at"], "text": c["text"],
             "path": c["path"], "line": c["line"], "parent": c["parent"],
             "updated": c.get("updated") or c["at"]}
            for c in pr["comments"]
            if c["author"]["id"] != author and not c.get("bot") and c["id"] not in resolved]


def sight_of(card: dict, entry: dict) -> dict:
    pr = sb_host.get(entry["repo"], entry["pr"])
    author = pr["author"]["id"]
    comments = comments_of(pr)
    # `state_at`: when this review's state was set (the sandbox host keeps it as `at`), which
    # is how the watcher's first look tells a review after Approve (c-604 review)
    reviews = [{"author": r["author"]["name"], "state": r["state"], "at": r["at"], "state_at": r["at"]}
               for r in pr["reviews"] if r["author"]["id"] != author]
    return {"state": pr["state"], "draft": bool(pr.get("draft")), "url": pr["url"], "head": pr["head"], "behind": behind(card, entry),
            "comments": comments, "reviews": reviews,
            "approvals": sum(r["state"] == "approved" for r in reviews), "ci": dict(pr.get("ci") or {"state": "none"})}


def sight(card: dict) -> dict:
    entries = entries_of(card)
    if len(entries) == 1:
        return sight_of(card, entries[0])
    parts = [dict(sight_of(card, e), repo=e["repo"], pr=e["pr"], primary=e["primary"]) for e in entries]
    states = {part["state"] for part in parts}
    state = "declined" if "declined" in states else ("merged" if states == {"merged"} else "open")
    return {"state": state, "url": parts[0]["url"], "head": parts[0]["head"], "prs": parts}


def diff(card: dict) -> str:
    entries, texts = entries_of(card), []
    for entry in entries:
        repo = repo_path(entry["repo"])
        git(repo, "fetch", "--quiet", "origin")
        shown = git(repo, "diff", f"origin/{base_of(card)}...origin/{entry['branch']}")
        if shown.returncode != 0:
            raise SandboxError(f"git diff in {entry['repo']}: {shown.stderr.strip()}")
        texts.append(shown.stdout if len(entries) == 1 else
                     f"# {entry['repo']}, pull request #{entry['pr']} ({entry['branch']})\n{shown.stdout}")
    text = "\n".join(texts)
    return text if len(text) <= DIFF_MAX else text[:DIFF_MAX] + f"\n[cut at {DIFF_MAX} characters]\n"


def trees_of(card: dict) -> list:
    return [tree for tree in (worktree_of(card, key) for key in repos_of(card)) if tree is not None]


def down(card: dict) -> dict:
    return {"down": [], "failed": [], "worktrees": [str(tree) for tree in trees_of(card)]}


def reap(card: dict) -> dict:
    """Remove the card's worktrees, only ones under the sandbox's `worktrees/` that git
    says are clean; anything else is kept and said why. Never deletes by hand."""
    removed, kept, inside = [], [], (home() / "worktrees").resolve()
    for key in repos_of(card):
        tree = worktree_of(card, key)
        if tree is None or not tree.exists():
            continue
        if not tree.resolve().is_relative_to(inside):
            kept.append({"path": str(tree), "why": "it is not a sandbox worktree"})
            continue
        status = git(tree, "status", "--porcelain")
        if status.returncode != 0 or status.stdout.strip():
            kept.append({"path": str(tree), "why": "it has uncommitted changes or git cannot read it"})
            continue
        gone = git(repo_path(key), "worktree", "remove", str(tree))
        if gone.returncode != 0:
            kept.append({"path": str(tree), "why": f"git worktree remove failed: {gone.stderr.strip()}"})
            continue
        removed.append(str(tree))
    return {"removed": removed, "kept": kept}


def matchable(card: dict) -> bool:
    derived = card.get("derived") or {}
    return not (option(card, "archived") or derived.get("archived") or is_tracking(card)
                or is_review(card) or is_research(card))


def branches_of(card: dict) -> set[str]:
    found = {str(option(card, "branch") or "")}
    for entry in (option(card, "prs") or {}).values():
        if isinstance(entry, dict) and entry.get("branch"):
            found.add(str(entry["branch"]))
    return {b for b in found if b}


def stories_of(card: dict) -> set[str]:
    texts = (option(card, "tracker_ref"), option(card, "branch"), card.get("title"), card.get("brief"))
    return {s for s in (story_of(t) for t in texts) if s}


def mine(cards: list[dict]) -> dict:
    candidates = [c for c in cards if isinstance(c, dict) and matchable(c)]
    rows = []
    for repo in sb_host.repos():
        for pr in sb_host.open_prs(repo):
            if pr["author"]["id"] != ME["id"]:
                continue
            row = {"repo": repo, "pr": pr["number"], "title": pr["title"], "branch": pr["branch"],
                   "draft": pr["draft"], "updated": pr["updated"], "url": pr["url"]}
            by_branch = [c["id"] for c in candidates if pr["branch"] in branches_of(c)]
            story = story_of(pr["branch"]) or story_of(pr["title"])
            by_story = [c["id"] for c in candidates if story and story in stories_of(c)]
            row["cards"], row["matched_by"] = ((by_branch, "branch") if by_branch else
                                               (by_story, "story" if by_story else None))
            tree = tree_path(repo, pr["branch"])
            row["worktree"] = str(tree) if (tree / ".git").exists() else None
            rows.append(row)
    return {"prs": rows}


# ----- review -----

def needs_him(pr: dict) -> bool:
    if ME["id"] not in pr["reviewers"] or pr["author"]["id"] == ME["id"]:
        return False
    return not any(r["author"]["id"] == ME["id"] and r["state"] == "approved" for r in pr["reviews"])


def scan() -> dict:
    rows, groups = [], {}
    for repo in sb_host.repos():
        for pr in sb_host.open_prs(repo):
            story = story_of(pr["branch"])
            if story:
                groups.setdefault(story, set()).add(repo)
            if needs_him(pr):
                rows.append({"key": f"{repo}:{pr['number']}", "repo": repo, "pr": pr["number"],
                             "title": pr["title"], "author": pr["author"]["name"],
                             "description": pr["description"][:4000], "created": pr["created"],
                             "updated": pr["updated"], "head": pr["head"], "branch": pr["branch"],
                             "base": pr["base"], "url": pr["url"], "group": story})
    return {"prs": rows, "open_groups": {s: sorted(r) for s, r in sorted(groups.items())}}


def poll_one(repo: str, number) -> dict:
    pr = sb_host.get(repo, int(number))
    return {"state": pr["state"], "head": pr["head"], "url": pr["url"]}


def poll(card: dict) -> dict:
    members = option(card, "review_members")
    if members:
        return {"members": {m["label"]: poll_one(m["repo"], m["pr"]) for m in members}}
    number = option(card, "pr")
    if not number:
        raise SandboxError(f"card {card['id']} names no pull request (options.pr)")
    return poll_one(repos_of(card)[0], number)


def branches(story: str, member_repos: list[str]) -> dict:
    found = {}
    for repo in sb_host.repos():
        if repo in member_repos:
            continue
        listed = git(origin_path(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads")
        found[repo] = [name for name in listed.stdout.split() if story_of(name) == story]
    return {"branches": found}


def story(story_id: str) -> dict:
    number = sb_tracker.number_of(story_id)
    found = sb_tracker.get(number) if number else None
    return {"title": (found or {}).get("title") or None}
