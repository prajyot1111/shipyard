"""`worktree <id>`: the card's worktrees, primary first, cut with plain git.

One worktree per repo, in the directory Keel gives a card everywhere else
(`adapters.worktree_dirs`: the repo's own `trees/<id>` on an install, else under the state
directory), on the card's branch: the local one, else the remote's, else a new one from the
remote's base (`options.base`, else the repo's default branch), cut with `--no-track` so a
bare `git push` in it can never be aimed at the base. The branch is named once and kept in
`options.branch`; the primary path goes in `options.worktree`, and a cross-repo card's in
`options.worktrees`, which is where Ship and the reap look. A review card (c-730) gets one
worktree detached at the change it reviews instead (`review.review_tree`).
"""

from pathlib import Path

from keel.packkit import card as gc
from keel.packkit import review, shared, ship
from keel.packkit.errors import HostError

FETCH_SECONDS = 120


def has_ref(repo: Path, ref: str) -> bool:
    return gc.git(repo, "show-ref", "--verify", "--quiet", ref).returncode == 0


def add(repo: Path, *args: str) -> None:
    added = gc.git(repo, "worktree", "add", "--quiet", *args)
    if added.returncode != 0:
        raise HostError(f"git worktree add in {repo.name}: {ship.git_said(added)}")


def cut_one(card: dict, key: str, dest: Path, branch: str) -> Path:
    """One repo's worktree on `branch`: reused when it is there, else cut."""
    if (dest / ".git").exists():
        return dest
    repo, remote = gc.repo_path(card, key), gc.remote_of(card)
    base = shared.base_in(card, key, writing=True)
    shared.refuse(card, key, branch)
    fetched = gc.git(repo, "fetch", "--quiet", "--prune", remote, timeout=FETCH_SECONDS)
    if fetched.returncode != 0:
        raise HostError(f"git fetch in {key}: {ship.git_said(fetched)}")
    gc.git(repo, "worktree", "prune")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if has_ref(repo, f"refs/heads/{branch}"):
        add(repo, str(dest), branch)
    elif has_ref(repo, f"refs/remotes/{remote}/{branch}"):
        add(repo, "-b", branch, str(dest), f"{remote}/{branch}")
    elif has_ref(repo, f"refs/remotes/{remote}/{base}"):
        add(repo, "--no-track", "-b", branch, str(dest), f"{remote}/{base}")
    else:
        raise HostError(f"{key} has no branch {base} on {remote} to cut {branch} from; "
                        f"set the card's base branch to one it has")
    return dest


def ensure_branch(card: dict) -> dict:
    if gc.option(card, "branch"):
        return card
    branch = gc.branch_for(card)
    gc.KB.set_option(card["id"], "branch", branch)
    return dict(card, options=dict(card.get("options") or {}, branch=branch))


def record(card: dict, keys: list[str], paths: list[Path]) -> None:
    if gc.option(card, "worktree") != str(paths[0]):
        gc.KB.set_option(card["id"], "worktree", str(paths[0]))
    if len(keys) > 1:
        recorded = {key: str(path) for key, path in zip(keys, paths)}
        if gc.option(card, "worktrees") != recorded:
            gc.KB.set_option(card["id"], "worktrees", recorded)


def worktrees_for(card: dict) -> list[Path]:
    keys = gc.repos_of(card)
    if not keys:
        raise HostError(f"card {card['id']} has no repo; an errand needs no worktree")
    if gc.is_review(card):
        return review.review_tree(card)       # c-730: detached at the change's head
    gc.base_option(card)        # a base that is no branch name is refused before anything is recorded
    card = ensure_branch(card)
    dirs = gc.engine().worktree_dirs(gc.keel_config(), card)
    paths = [cut_one(card, key, Path(dest), gc.branch_in(card, key)) for key, dest in zip(keys, dirs)]
    record(card, keys, paths)
    return paths
