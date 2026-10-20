"""What the host says about a shipping card's change, in the engine's words: `ship`.

- `ship <id> poll`: a SIGHT (`keel/shipwatch.py` has the shape). Its state (`open`,
  `merged`, or `declined` for one closed without merging), whether it is a draft, its
  address, its head commit, the branch it merges into, how far it is behind that branch,
  what other people said, each reviewer's standing review, the approvals, and the checks on
  the head commit. A card with one per repo is seen as `{state, url, head, prs: [...]}`.
- `ship <id> diff`: each change's diff against its base, from the repo's clone.
- `ship <id> down`: nothing to stop, no pack on the kit runs containers.
- `ship <id> reap`: a done card's worktrees removed, one with changes kept.
- `ship mine`: the signed-in account's open changes in the space's repos, each with the
  cards whose branch it is.

Reads only, but for `reap`, which removes clean worktrees on this disk.

**What counts as said.** A general comment, a comment on a line, and the words a review was
submitted with are all comments here. Left out: the change author's own, a bot's (the layer
says which, `bot`), and every line comment the layer marks resolved. A reviewer's standing
review is their newest approval or request for changes; a dismissed one is none.

**Three id spaces.** A host may number general comments, line comments and reviews
separately, so one number may be two things on one change. A comment's `id` here says its
kind: `g<n>` (general), `l<n>` (on a line) and `r<n>` (a review's words). The engine makes
the handle `c` and the id (`cg101`, `cl201`, `cr301`), and Ship routes a reply by that kind.
"""

from keel.packkit import card as gc
from keel.packkit import pack, shared, ship
from keel.packkit.errors import HostError
from keel.packkit.layer import PARTS, UNKNOWN, fold_checks

DIFF_MAX = 80000
REMOTE_SECONDS = 45
STANDING = ("approved", "changes_requested")


# ----- who and what -----

def general(row: dict, kind: str = "g") -> dict:
    return {"id": f"{kind}{int(row['id'])}", "author": row.get("author") or "someone", "at": row.get("at"),
            "text": row.get("body") or "", "path": None, "line": None, "parent": None,
            "updated": row.get("updated") or row.get("at")}


def on_line(row: dict) -> dict:
    under = row.get("parent")
    return dict(general(row, "l"), path=row.get("path"), line=row.get("line"),
                parent=f"cl{int(under)}" if under else None)   # the HANDLE of the comment it is under


def with_words(row: dict) -> dict:
    """A review's own words, kept as a general comment under the review's id."""
    return dict(general(row, "r"), at=row.get("at"), updated=row.get("at"))


def comments_of(said: dict, author: str | None) -> list[dict]:
    """Someone else's live words, each kind in its own id space, in the order they were
    said (ids sort as text, `g10` before `g9`, so they are only the tie-break)."""
    theirs = lambda row: row.get("author") != author and not row.get("bot")   # noqa: E731
    out = [general(row) for row in said.get("general") or [] if theirs(row)]
    out += [on_line(row) for row in said.get("lines") or [] if theirs(row) and not row.get("resolved")]
    out += [with_words(row) for row in said.get("reviews") or []
            if theirs(row) and (row.get("body") or "").strip() and row.get("state") != "pending"]
    return sorted(out, key=lambda one: (str(one.get("at") or ""), one["id"]))   # as they were said


def reviews_of(submitted: list[dict], author: str | None) -> list[dict]:
    """Each reviewer's standing review: the newest approval or request for changes, and
    none once it was dismissed. A review that only commented changes nothing."""
    standing = {}
    for row in sorted(submitted, key=lambda one: str(one.get("at") or "")):
        who, state = row.get("author"), row.get("state")
        if not who or who == author or row.get("bot"):
            continue
        if row.get("dismissed"):
            standing.pop(who, None)
        elif state in STANDING:
            standing[who] = {"author": who, "state": state, "at": row.get("at"), "state_at": row.get("at")}
    return list(standing.values())


# ----- ship poll -----

def behind(card: dict, entry: dict, base: str | None) -> int | None:
    """Commits on the base the change's branch does not have, from the repo's own clone
    after a fetch of the two branches (remote-tracking refs only). None when git cannot say.
    The base is the card's `options.base` first, then the change's own."""
    try:
        repo, remote = gc.repo_path(card, entry["repo"]), gc.remote_of(card)
        base = gc.base_option(card) or base or shared.base_in(card, entry["repo"])
        gc.fetch(repo, remote, base, entry["branch"], timeout=REMOTE_SECONDS)
        counted = gc.git(repo, "rev-list", "--count", f"{remote}/{entry['branch']}..{remote}/{base}")
    except HostError:
        return None
    out = counted.stdout.strip()
    return int(out) if counted.returncode == 0 and out.isdigit() else None


def named(value) -> str | None:
    """A branch name the host gave, when git would take it as one; else None, so a name
    that reads as an option never reaches git here or in the engine."""
    try:
        return gc.ref_name(value) if value else None
    except HostError:
        return None


def sight_of(card: dict, entry: dict) -> dict:
    repo, number, layer = gc.host_repo(card, entry["repo"]), int(entry["pr"]), pack.layer()
    seen = layer.get(repo, number, sight=True)
    if seen["state"] == UNKNOWN:
        raise gc.unknown_state(repo, number)
    unnamed = bool(seen["base"]) and named(seen["base"]) is None
    seen["base"], seen["branch"] = named(seen["base"]), named(seen["branch"])
    said = layer.said(repo, number, parts=PARTS)
    reviews = reviews_of(said.get("reviews") or [], seen.get("author"))
    return {"state": seen["state"], "draft": seen["draft"], "url": seen["url"], "head": seen["head"],
            "base": seen["base"],
            "behind": None if unnamed else behind(card, dict(entry, branch=seen["branch"] or entry["branch"]),
                                                  seen["base"]),
            "comments": comments_of(said, seen.get("author")),
            "reviews": reviews, "approvals": sum(r["state"] == "approved" for r in reviews),
            "ci": fold_checks(layer.checks(repo, seen))}


def sight(card: dict) -> dict:
    entries = ship.entries_of(card)
    if len(entries) == 1:
        return sight_of(card, entries[0])
    parts = [dict(sight_of(card, e), repo=e["repo"], pr=e["pr"], primary=e["primary"]) for e in entries]
    states = {part["state"] for part in parts}
    state = "declined" if "declined" in states else ("merged" if states == {"merged"} else "open")
    return {"state": state, "url": parts[0]["url"], "head": parts[0]["head"], "prs": parts}


# ----- ship diff, down, reap -----

def diff(card: dict) -> str:
    entries, texts = ship.entries_of(card), []
    for entry in entries:
        repo, remote = gc.repo_path(card, entry["repo"]), gc.remote_of(card)
        base = shared.base_in(card, entry["repo"])
        gc.fetch(repo, remote, base, entry["branch"], timeout=REMOTE_SECONDS)
        shown = gc.git(repo, "diff", f"{remote}/{base}...{remote}/{entry['branch']}")
        if shown.returncode != 0:
            raise HostError(f"git diff in {entry['repo']}: {ship.git_said(shown)}")
        texts.append(shown.stdout if len(entries) == 1 else
                     f"# {entry['repo']}, {pack.words().change} #{entry['pr']} ({entry['branch']})\n{shown.stdout}")
    text = "\n".join(texts)
    return text if len(text) <= DIFF_MAX else text[:DIFF_MAX] + f"\n[cut at {DIFF_MAX} characters]\n"


def trees_of(card: dict) -> list[tuple[str, object]]:
    keys = list(dict.fromkeys(gc.repos_of(card) + [entry["repo"] for entry in gc.prs_of(card)]))
    return [(key, tree) for key, tree in ((key, gc.worktree_of(card, key)) for key in keys) if tree is not None]


def down(card: dict) -> dict:
    return {"down": [], "failed": [], "worktrees": [str(tree) for _, tree in trees_of(card)]}


def linked(repo, tree) -> bool:
    """True when git lists `tree` as a worktree of `repo` that is not the clone itself."""
    listed = gc.git(repo, "worktree", "list", "--porcelain").stdout.splitlines()
    paths = [line[len("worktree "):] for line in listed if line.startswith("worktree ")]
    return str(tree.resolve()) in paths[1:]      # the first one listed is the clone itself


def reap(card: dict) -> dict:
    """A DONE card's recorded worktrees removed with `git worktree remove` (never forced,
    never by hand): one with uncommitted changes, or one git does not list as a worktree of
    its repo, is kept and said why."""
    if card.get("stage") != "done":
        raise HostError(f"{card['id']} is at {card.get('stage')}; only a done card's worktree is reaped")
    removed, kept = [], []
    for key, tree in trees_of(card):
        if not tree.exists():
            continue
        repo = gc.repo_path(card, key)
        if not linked(repo, tree):
            kept.append({"path": str(tree), "why": f"git does not list it as a worktree of {key}"})
            continue
        status = gc.git(tree, "status", "--porcelain")
        if status.returncode != 0 or status.stdout.strip():
            kept.append({"path": str(tree), "why": "it has uncommitted changes"})
            continue
        gone = gc.git(repo, "worktree", "remove", str(tree))
        if gone.returncode != 0:
            kept.append({"path": str(tree), "why": f"git worktree remove failed: {ship.git_said(gone)}"})
            continue
        removed.append(str(tree))
    return {"removed": removed, "kept": kept}


# ----- ship mine -----

def matchable(card: dict) -> bool:
    derived = card.get("derived") or {}
    return not (gc.option(card, "archived") or derived.get("archived") or gc.is_tracking(card)
                or gc.is_research(card) or gc.is_review(card))


def branches_of(card: dict) -> set[str]:
    found = {str(gc.option(card, "branch") or "")}
    for entry in (gc.option(card, "prs") or {}).values():
        if isinstance(entry, dict) and entry.get("branch"):
            found.add(str(entry["branch"]))
    return {branch for branch in found if branch}


def tree_on(repo, branch: str) -> str | None:
    """The worktree git has `branch` checked out in, when there is one."""
    path = None
    for line in gc.git(repo, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}":
            return path
    return None


def mine(cards: list[dict], space: str) -> dict:
    """`{prs: [{repo, pr, title, branch, draft, updated, url, worktree, cards, matched_by}]}`
    for every open change the signed-in account wrote in the space's repos on the host. A
    card is matched by its branch only: the kit has no tracker to match a ticket by."""
    candidates = [card for card in cards if isinstance(card, dict) and matchable(card)]
    found = gc.keel_config().spaces.get(space)
    if found is None:
        raise HostError(f"this config has no space {space!r}")
    rows = []
    for key, path in found.repos.items():
        repo, _ = gc.clone_repo(path, getattr(found, "remote", None) or "origin")
        if not repo:
            continue                        # a repo that is not on the host has none to list
        for pr in pack.layer().mine(repo):
            branch = pr.get("branch") or ""
            cards_on = [card["id"] for card in candidates if branch and branch in branches_of(card)]
            rows.append({"repo": key, "pr": int(pr["id"]), "title": pr.get("title") or "",
                         "branch": branch, "draft": bool(pr.get("draft")), "updated": pr.get("updated"),
                         "url": pr.get("url") or pack.host().pr_url(repo, pr["id"]),
                         "worktree": tree_on(path, branch) if branch else None,
                         "cards": cards_on, "matched_by": "branch" if cards_on else None})
    return {"prs": rows}
