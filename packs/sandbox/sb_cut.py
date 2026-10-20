"""`worktree <id>`: the sandbox card's worktrees, primary first, cut with plain git.

A code card gets one worktree per repo under `<sandbox>/worktrees/<repo>/<branch slug>`, on
its branch (the local one, else origin's, else a new one from `origin/<base>`), after the
story is minted when the card asks for one. The branch is named once and kept in
`options.branch`; the primary path goes in `options.worktree`, and a cross-repo card's in
`options.worktrees`, which is where the lint and a review round's push look.

A review card gets a DETACHED worktree at its pull request's head, `options.worktree` and
`options.review_head` recorded, so the deck can draw each finding's lines from it.
"""

from pathlib import Path

import sb_host
import sb_tracker
from sb_card import (KB, TRACKER_CREATE, SandboxError, base_of, branch_for, branch_in, git,
                     home, is_review, kind_of, option, primary_repo, repo_path, repos_of)


def tree_path(repo: str, name: str) -> Path:
    return home() / "worktrees" / repo / name.replace("/", "-")


def fetch(repo: Path) -> None:
    fetched = git(repo, "fetch", "--quiet", "--prune", "origin")
    if fetched.returncode != 0:
        raise SandboxError(f"git fetch in {repo}: {fetched.stderr.strip()}")


def has_ref(repo: Path, ref: str) -> bool:
    return git(repo, "show-ref", "--verify", "--quiet", ref).returncode == 0


def add(repo: Path, *args: str) -> None:
    added = git(repo, "worktree", "add", "--quiet", *args)
    if added.returncode != 0:
        raise SandboxError(f"git worktree add {' '.join(args)}: {added.stderr.strip()}")


def cut_one(key: str, branch: str, base: str) -> Path:
    """One repo's worktree on `branch`: reused when there, else cut."""
    repo, dest = repo_path(key), tree_path(key, branch)
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fetch(repo)
    if has_ref(repo, f"refs/heads/{branch}"):
        add(repo, str(dest), branch)
    elif has_ref(repo, f"refs/remotes/origin/{branch}"):
        add(repo, "-b", branch, str(dest), f"origin/{branch}")
    else:
        add(repo, "-b", branch, str(dest), f"origin/{base}")
    return dest


def ensure_story(card: dict) -> dict:
    if option(card, "tracker_mode") != TRACKER_CREATE or option(card, "tracker_ref"):
        return card
    story = sb_tracker.mint(card.get("title", ""), kind_of(card))
    KB.set_option(card["id"], "tracker_ref", story["ref"])
    KB.note(card["id"], f"minted tracker story {story['ref']} ({sb_tracker.url(story['number'])})")
    return dict(card, options=dict(card.get("options") or {}, tracker_ref=story["ref"]))


def ensure_branch(card: dict) -> dict:
    branch = branch_for(card)
    if not option(card, "branch"):
        KB.set_option(card["id"], "branch", branch)
        card = dict(card, options=dict(card.get("options") or {}, branch=branch))
    return card


def record(card: dict, keys: list[str], paths: list[Path]) -> None:
    if option(card, "worktree") != str(paths[0]):
        KB.set_option(card["id"], "worktree", str(paths[0]))
    if len(keys) > 1:
        recorded = {key: str(path) for key, path in zip(keys, paths)}
        if option(card, "worktrees") != recorded:
            KB.set_option(card["id"], "worktrees", recorded)


def review_tree(card: dict) -> list[Path]:
    """A detached worktree at the reviewed pull request's head."""
    key, number = primary_repo(card), option(card, "pr")
    if not number:
        raise SandboxError(f"review card {card['id']} names no pull request (options.pr)")
    pr = sb_host.get(key, int(number))
    repo, dest = repo_path(key), tree_path(key, f"review-{int(number)}")
    fetch(repo)
    if (dest / ".git").exists():
        moved = git(dest, "checkout", "--quiet", "--detach", pr["head"])
        if moved.returncode != 0:
            raise SandboxError(f"moving {dest} to {pr['head'][:10]}: {moved.stderr.strip()}")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        add(repo, "--detach", str(dest), pr["head"])
    record(card, [key], [dest])
    if option(card, "review_head") != pr["head"]:
        KB.set_option(card["id"], "review_head", pr["head"])
    return [dest]


def worktrees_for(card: dict) -> list[Path]:
    keys = repos_of(card)
    if not keys:
        raise SandboxError(f"card {card['id']} has no repo; an errand needs no worktree")
    if is_review(card):
        return review_tree(card)
    card = ensure_branch(ensure_story(card))
    paths = [cut_one(key, branch_in(card, key), base_of(card)) for key in keys]
    record(card, keys, paths)
    return paths
