"""Review cards (c-730): a change that waits on your review becomes a card, its house
reviews it in a read-only checkout, and your Approve posts what you kept.

The engine's half is `keel/reviewcards.py` (the drain files and tends the cards) and
`keel/reviewround.py` (what you kept, as the answer `publish --answer` is handed). This is
the pack's half, in the shapes the engine reads:

- `review scan` prints `{prs, open_groups}`: every OPEN change in the space's repos on the
  host that asks the signed-in account for its review (the layer's `review_requests`), each
  in the engine's words. There is no story to group changes by, so no row has a `group` and
  `open_groups` is empty: every card reviews one change.
- `review <id> poll` prints `{state, head, url}` for one card's change; a state the host
  does not name is refused, never read as open.
- `review_tree` is `worktree` for a review card: one worktree DETACHED at the change's head,
  fetched from the host's own ref for it (`HostConfig.pull_head_ref`), so a fork's change is
  reviewed the same way and nothing in it is a branch of anyone's.
- `post` is Approve outcome on a review card: ONE review (the layer's `post_review`), the
  kept findings at their lines, the summary as its body and the verdict as its event. One
  call, so it lands whole or not at all; its body ends with a hidden marker naming the card
  and the round, so a retry finds the review that landed and posts nothing twice.

The space a scan answers for is `KEEL_SPACE` (`keel/adapters.py`), since a pack may serve
several; run by hand, it is the one space on this pack that asks for reviews.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

from keel.packkit import card as gc
from keel.packkit import cli, pack
from keel.packkit.errors import HostError, OutsideChange
from keel.packkit.layer import REVIEWS, UNKNOWN

DESCRIPTION_MAX = 4000
FETCH_SECONDS = 120
MARK = "<!-- keel:review {card} round {round} -->"


# ----- which space -----

def space_named() -> str:
    """The space this verb answers for: `KEEL_SPACE`, else the one space on this pack that
    asks for reviews."""
    cfg, named = gc.keel_config(), os.environ.get("KEEL_SPACE") or ""
    mine = gc.on_pack(cfg)
    if named:
        if named not in mine:
            raise HostError(f"the {named} space is not on this pack")
        return named
    asking = [name for name in mine if getattr(cfg.spaces[name], "review_scan", False)]
    if len(asking) != 1:
        raise HostError(f"{len(asking)} spaces on this pack ask for reviews; say which with KEEL_SPACE")
    return asking[0]


# ----- review scan -----

def row_of(key: str, repo, pr: dict) -> dict:
    number = int(pr["id"])
    return {"key": f"{key}:{number}", "repo": key, "pr": number, "title": pr.get("title") or "",
            "author": pr.get("author") or "someone",
            "description": str(pr.get("body") or "")[:DESCRIPTION_MAX],
            "created": pr.get("created"), "updated": pr.get("updated"), "head": pr.get("head"),
            "branch": pr.get("branch"), "base": pr.get("base"),
            "url": pr.get("url") or pack.host().pr_url(repo, number), "group": None,
            # r1.F1: a fork's code is not the team's; one the host does not call its own is a fork
            "fork": pr.get("own") is not True}


def scan() -> dict:
    """Every open change in the space's repos that asks for your review."""
    space = gc.keel_config().spaces[space_named()]
    rows, failed, repos = [], [], gc.space_repos(space)
    for key, repo in repos:
        try:
            found = pack.layer().review_requests(repo)
        except HostError as error:
            # r1.F3: one repo the host will not answer for is skipped and said, so the space's
            # other review cards keep their pass
            print(f"review: {key} was not scanned: {error}", file=sys.stderr)
            failed.append(key)
            continue
        rows += [row_of(key, repo, pr) for pr in found]
    if repos and len(failed) == len(repos):
        raise HostError(f"no repo of the space could be scanned ({', '.join(failed)})")
    return {"prs": rows, "open_groups": {}}


# ----- review <id> poll -----

def pull_of(card: dict) -> tuple:
    number = gc.option(card, "pr")
    if not number:
        raise HostError(f"review card {card['id']} names no {pack.words().change} (options.pr)")
    return gc.host_repo(card, gc.primary_repo(card)), int(number)


def poll(card: dict) -> dict:
    repo, number = pull_of(card)
    found = pack.layer().get(repo, number)
    if found["state"] == UNKNOWN:
        raise gc.unknown_state(repo, number)
    return {"state": found["state"], "head": found["head"], "url": found["url"]}


# ----- the house: a detached checkout at the change's head -----

def review_tree(card: dict) -> list[Path]:
    """The review card's one worktree, detached at the change's head as the host has it
    now: cut once, then moved on a re-review. `options.worktree` and `options.review_head`
    record where and at what."""
    key, w = gc.primary_repo(card), pack.words()
    host, number = pull_of(card)
    found = pack.layer().get(host, number)
    head, repo, remote = found["head"], gc.repo_path(card, key), gc.remote_of(card)
    if not head:
        raise HostError(f"{w.host} named no head commit for {w.change} #{number} of {host}")
    ref = pack.host().pull_head_ref.format(n=number)
    fetched = gc.git(repo, "fetch", "--quiet", remote, ref, timeout=FETCH_SECONDS)
    if fetched.returncode != 0 or gc.git(repo, "cat-file", "-e", f"{head}^{{commit}}").returncode != 0:
        why = (fetched.stderr.strip() or "the head commit did not arrive").splitlines()[-1]
        raise HostError(f"{w.change} #{number}'s head could not be fetched into {key}: {cli.sentence(why)}")
    if found.get("base"):
        gc.fetch(repo, remote, found["base"], timeout=FETCH_SECONDS)      # for the diff; best effort
    dest = Path(gc.engine().worktree_dirs(gc.keel_config(), card)[0])
    if (dest / ".git").exists():
        moved = gc.git(dest, "checkout", "--quiet", "--detach", head)
        if moved.returncode != 0:
            raise HostError(f"the review worktree could not move to {head[:12]}: {cli.sentence(moved.stderr)}")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        gc.git(repo, "worktree", "prune")
        added = gc.git(repo, "worktree", "add", "--quiet", "--detach", str(dest), head)
        if added.returncode != 0:
            raise HostError(f"git worktree add in {key}: {cli.sentence(added.stderr)}")
    for name, value in (("worktree", str(dest)), ("review_head", head)):
        if gc.option(card, name) != value:
            gc.KB.set_option(card["id"], name, value)
    return [dest]


# ----- Approve outcome: the review you kept, posted once -----

def marker(card: dict, review: dict) -> str:
    return MARK.format(card=card["id"], round=int(review.get("round") or 1))


def landed(repo, number: int, mark: str) -> dict | None:
    """The review of this card and round the signed-in account already posted, or None."""
    layer = pack.layer()
    me = layer.account(repo)
    found = layer.said(repo, number, parts=(REVIEWS,)).get(REVIEWS) or []
    return next((one for one in found if one.get("author") == me and mark in (one.get("body") or "")), None)


def placed(comments: list[dict]) -> list[dict]:
    """The findings that have a place: `{path, line, text}`."""
    return [{"path": one["path"], "line": int(one["line"]), "text": one["text"]}
            for one in comments if one.get("path") and one.get("line")]


def folded(summary: str, comments: list[dict]) -> str:
    """The summary with every finding under it, each named by its place: what is posted
    when the host will not put a finding on its line."""
    lines = [summary.strip()] if summary.strip() else []
    for one in comments:
        place = f"`{one['path']}:{one['line']}`" if one.get("path") and one.get("line") else "General"
        lines.append(f"**{place}**\n\n{one['text'].strip()}")
    return "\n\n".join(lines)


def post(card: dict, review: dict) -> dict:
    """Your kept findings inline, the summary and the verdict, as ONE review on the change.
    Refused on one that is no longer open; posts nothing when this round's review has
    already landed."""
    repo, number = pull_of(card)
    w, layer = pack.words(), pack.layer()
    if review.get("members"):
        raise HostError(f"a review of several {w.changes} at once is not one this pack posts")
    mark, comments = marker(card, review), list(review.get("comments") or [])
    verdict = review.get("verdict") if review.get("verdict") in ("approve", "changes") else "comment"
    summary = str(review.get("summary") or "")
    # r1.F4: what already landed is recorded whatever the state; only a new post needs it open
    done, how = landed(repo, number, mark), "inline"
    if done is None:
        state = layer.get(repo, number)["state"]
        if state != "open":
            raise HostError(f"{w.change} #{number} of {repo} is {state}, so no review was posted")
        try:
            done = layer.post_review(repo, number, f"{summary}\n\n{mark}".strip(), verdict, placed(comments),
                                     review.get("head"))
        except OutsideChange:
            if not placed(comments):
                raise
            done, how = layer.post_review(repo, number, f"{folded(summary, comments)}\n\n{mark}", verdict, [],
                                          review.get("head")), "summary"
    posted = {"head": review.get("head"), "round": review.get("round"), "review": done.get("id"),
              "comments": {one["row"]: how for one in comments if one.get("row")},
              "summary": done.get("id"), "verdict": verdict, "severity": review.get("severity"),
              "ledger": review.get("ledger") or [], "url": done.get("url"),
              "at": datetime.now().astimezone().isoformat(timespec="seconds")}
    gc.KB.set_option(card["id"], "review_posted", posted)
    gc.KB.note(card["id"], f"review posted on {w.change} #{number}: {len(comments)} finding"
                           f"{'s' if len(comments) != 1 else ''} {'inline' if how == 'inline' else 'in its summary'}, "
                           f"verdict {verdict}")
    return {"published": "review", "pr": number, "comments": len(comments), "verdict": verdict}
