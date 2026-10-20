"""`pr`, `publishable` and `publish`: the sandbox card's pull requests, one per repo.

The same rules as the work adapter, over the JSON code host:

- `pr --draft` opens a draft in every repo whose branch is on origin (the body is the repo's
  ```copy block under `## PR body` in the record, else the first, else the card), records
  each and prints the URLs; `pr --ready` flips them all.
- `publishable` holds the card at `kb stage review` until every repo's branch is on origin
  with its head, and a pull request is open.
- `publish` (his Approve outcome) flips every draft ready, moves the story, writes one note
  and answers `"shipping": true`. With `--answer` it runs his Ship on a card at shipping
  (`{"ship": true, "replies"}`: every handle and worktree checked, then each branch pushed,
  each draft flipped ready and each kept reply posted once, c-600), or posts a review
  card's kept findings, summary and verdict, each recorded as it lands so a retry says
  nothing twice.
"""

import re
import subprocess
from datetime import datetime

import sb_host
import sb_tracker
from sb_card import (KB, SandboxError, base_of, branch_in, context_text, git, is_research,
                     is_review, is_tracking, kind_of, option, primary_repo, prs_of, record_pr,
                     recorded_pr, refuse_no_pr, repo_path, repos_of, story_of, worktree_of)


# ----- the body -----

COPY_OPEN = re.compile(r"^(?P<ticks>`{3,}|~{3,})\s*copy\b(?P<title>[^\n]*)$")


def copy_blocks(section: str) -> list[tuple[str, str]]:
    """(title, text) of each ```copy fence at the top of a section, in order."""
    lines, out, index = section.split("\n"), [], 0
    while True:
        while index < len(lines) and not lines[index].strip():
            index += 1
        opened = COPY_OPEN.match(lines[index].strip()) if index < len(lines) else None
        if not opened:
            return out
        close = next((at for at in range(index + 1, len(lines)) if lines[at].strip() == opened["ticks"]), None)
        if close is None:
            return out
        out.append((opened["title"].strip(), "\n".join(lines[index + 1:close]).strip()))
        index = close + 1


def body_section(text: str, repo: str | None = None) -> str | None:
    match = re.search(r"^##\s*PR body[^\n]*\n(.*)\Z", text, re.S | re.M | re.I)
    if not match:
        return None
    blocks = copy_blocks(match.group(1))
    if blocks and repo:
        word = re.compile(rf"(?<![\w-]){re.escape(repo)}(?![\w-])", re.I)
        named = [body for title, body in blocks if word.search(title)]
        if named:
            return named[0]
    body = blocks[0][1] if blocks else match.group(1).strip()
    return body or None


def body_for(card: dict, repo: str) -> str:
    found = body_section(context_text(card["id"]), repo)
    return found or f"{card.get('title', '')}\n\n{(card.get('brief') or '').strip()}\n\nShipyard card {card['id']}.\n"


def title_for(card: dict) -> str:
    story = story_of(option(card, "tracker_ref"))
    return f"{kind_of(card)}: {card.get('title', '').strip()}" + (f" [{story}]" if story else "")


# ----- open and ready -----

def open_drafts(card: dict) -> dict:
    refuse_no_pr(card)
    keys, opened, skipped = repos_of(card) or [primary_repo(card)], [], []
    for repo in keys:
        branch = branch_in(card, repo)
        number = recorded_pr(card, repo)
        if number:
            found = sb_host.get(repo, number)
        else:
            found = sb_host.find_open(repo, branch)
            if found is None:
                if sb_host.origin_head(repo, branch) is None:
                    if len(keys) == 1:
                        raise SandboxError(f"branch {branch} is not on origin yet: push it first")
                    skipped.append({"repo": repo, "why": f"branch {branch} is not on origin yet"})
                    continue
                found = sb_host.open_pr(repo, title_for(card), branch, base_of(card), body_for(card, repo))
            card = record_pr(card, repo, found["number"])
            named = f"{repo} " if len(keys) > 1 else ""
            KB.note(card["id"], f"{named}{'draft ' if found['draft'] else ''}pull request #{found['number']}: {found['url']}")
        opened.append({"id": found["number"], "url": found["url"], "draft": found["draft"], "repo": repo})
    if not opened:
        raise SandboxError("no branch is on origin yet in " + ", ".join(one["repo"] for one in skipped))
    return {"opened": opened, "skipped": skipped}


def make_ready(card: dict) -> list[dict]:
    """Every repo's pull request found first, then each flipped ready: one missing flips none."""
    refuse_no_pr(card)
    keys, found = repos_of(card) or [primary_repo(card)], []
    for repo in keys:
        number = recorded_pr(card, repo)
        if not number:
            hit = sb_host.find_open(repo, branch_in(card, repo))
            if hit is None:
                where = f" in {repo}" if len(keys) > 1 else ""
                raise SandboxError(f"card {card['id']} has no pull request{where} to mark ready")
            number = hit["number"]
            card = record_pr(card, repo, number)
        found.append((repo, int(number)))
    return [dict(sb_host.set_draft(repo, number, False), repo=repo) for repo, number in found]


# ----- publishable -----

def code_card(card: dict) -> bool:
    return bool(repos_of(card)) and not (is_research(card) or is_tracking(card) or is_review(card))


def missing(card: dict) -> str | None:
    """What stops this card's outcome being published, in one line, or None."""
    if not code_card(card):
        return None
    keys = repos_of(card)
    for key in keys:
        branch, where = branch_in(card, key), f" in {key}" if len(keys) > 1 else ""
        remote = sb_host.origin_head(key, branch)
        if remote is None:
            return (f"{card['id']} is not publishable: branch {branch} is not on origin{where}. "
                    f"Push it (`git push -u origin {branch}`), open the draft (`pr {card['id']} --draft`), "
                    f"then stage review.")
        local = git(repo_path(key), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").stdout.strip()
        if local and local != remote and git(repo_path(key), "merge-base", "--is-ancestor", local, remote).returncode != 0:
            return f"{card['id']} is not publishable: {branch}{where} has commits origin does not; push again."
        if recorded_pr(card, key):
            continue
        found = sb_host.find_open(key, branch)
        if found is None:
            return (f"{card['id']} is not publishable: no pull request is open from {branch}{where}. "
                    f"Open it (`pr {card['id']} --draft`), then stage review.")
        card = record_pr(card, key, found["number"])
    return None


def unpublished(card: dict) -> str | None:
    """The deck's line for a code card at his gate lacking a pull request: card fields only."""
    if card.get("stage") != "review" or not code_card(card):
        return None
    have = {entry["repo"] for entry in prs_of(card)}
    if not have:
        return ("Not publishable: no pull request is open for it, and Approve only flips a draft "
                "to ready. Send back so its house pushes the branch and opens the draft.")
    lacking = [key for key in repos_of(card) if key not in have]
    if not lacking:
        return None
    return (f"Not publishable: no pull request is recorded for {', '.join(lacking)}, and Approve "
            f"flips every repo's draft to ready. Send back so its house opens it there.")


# ----- publish -----

def refuse_unless_shipping_tap(card: dict, verb: str) -> None:
    """As the work adapter's `fence.refuse_unless_shipping_tap`: at shipping, `pr` never
    runs and `publish` only inside his Ship (the card's `options.publishing` marker)."""
    if card.get("stage") != "shipping":
        return
    if verb == "publish" and option(card, "publishing"):
        return
    raise SandboxError(f"{card['id']} is at shipping: only the user's Ship pushes its commits or writes "
                       f"to its pull request")


def publish(card: dict, answer: dict | None = None) -> dict:
    answer = answer or {}
    if "review" in answer:
        return post_review(card, answer["review"])
    if is_tracking(card):
        KB.note(card["id"], "tracking card closed: every slice published its own")
        return {"published": "nothing", "kind": "tracking"}
    if is_research(card):
        KB.note(card["id"], "research outcome accepted: nothing was published")
        return {"published": "nothing", "kind": "research"}
    refuse_unless_shipping_tap(card, "publish")
    if "ship" in answer:
        return ship(card, answer)
    ready = make_ready(card)
    result = {"pr": ready[0]["number"], "url": ready[0]["url"], "draft": ready[0]["draft"], "shipping": True}
    heads = {one["repo"]: one["head"] for one in ready if one.get("head")}
    if heads:
        result["heads"] = heads      # his first Ship leases against these (c-600 review)
    if len(ready) > 1:
        result["prs"] = [{"repo": one["repo"], "pr": one["number"], "url": one["url"], "draft": one["draft"]}
                         for one in ready]
    number = sb_tracker.number_of(story_of(option(card, "tracker_ref")))
    if number and sb_tracker.get(number):
        moved = sb_tracker.move(number, "in review")
        result["story"], result["story_state"] = moved["ref"], moved["state"]
    KB.note(card["id"], publish_note(result))
    return result


def publish_note(result: dict) -> str:
    if result.get("prs"):
        text = "published: pull requests " + ", ".join(
            f"{one['repo']} #{one['pr']} ({one['url']})" for one in result["prs"]) + " ready for review"
    else:
        text = f"published: pull request #{result['pr']} ready for review ({result['url']})"
    if result.get("story"):
        text += f"; story {result['story']} moved to {result['story_state']}"
    return text


# ----- his Ship on a card at shipping -----

def target(entries: list[dict], handle: str) -> tuple[dict, str]:
    """The pull request a reply goes to and its handle there: `<repo>.<handle>` names one of
    the card's other pull requests, no dot the primary's; a dotted one naming none is refused."""
    repo, dot, local = handle.partition(".")
    if not dot:
        return entries[0], handle
    for entry in entries[1:]:
        if entry["repo"] == repo:
            return entry, local
    raise SandboxError(f"the reply {handle} names {repo}, which is not one of this card's other pull "
                       f"requests; nothing was pushed or posted")


def ship_trees(card: dict, entries: list[dict]) -> list[tuple[dict, object]]:
    """(pull request, worktree) for each, every one checked on its branch before any push."""
    trees = []
    for entry in entries:
        tree = worktree_of(card, entry["repo"])
        if tree is None or not (tree / ".git").exists():
            if entry["primary"]:
                raise SandboxError(f"card {card['id']} has no worktree to push from")
            continue
        here = git(tree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if here != entry["branch"]:
            raise SandboxError(f"the {entry['repo']} worktree is on {here or 'no branch'}, not {entry['branch']}; nothing was pushed")
        trees.append((entry, tree))
    return trees


FETCH_SECONDS = 45     # shorter than the push's 180: a remote that hangs leaves the push its time
DIVERGED = ("the {repo} worktree has diverged from {branch} on the remote: that branch was rewritten "
            "or pushed to outside Shipyard, so nothing was pushed and no reply was posted. Bring the "
            "worktree in line first (the card shows the commands)")


def standing(tree, branch: str) -> tuple[str, str | None]:
    """As the work adapter's `prsend.standing` (c-653): the worktree against the pull
    request's branch ON THE REMOTE, asked now. `forward` (the remote's head is HEAD or an
    ancestor of it), `skip` (the remote holds HEAD and more), `diverged`, or `unknown` when
    the fetch failed or hung, and then the push is attempted and says what is wrong."""
    try:
        fetched = git(tree, "fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                      timeout=FETCH_SECONDS)
    except subprocess.TimeoutExpired:
        return "unknown", None
    if fetched.returncode != 0:
        return "unknown", None
    head = git(tree, "rev-parse", "HEAD").stdout.strip()
    there = git(tree, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}").stdout.strip()
    if not head or not there:
        return "unknown", None
    if git(tree, "merge-base", "--is-ancestor", there, head).returncode == 0:
        return "forward", there
    if git(tree, "merge-base", "--is-ancestor", head, there).returncode == 0:
        return "skip", there
    return "diverged", there


def push_all(trees: list, lease: dict | None = None) -> dict:
    """As the work adapter's `prsend.push`: every worktree looked at first, a diverged one
    refusing the whole Ship; then each push plain (a fast-forward, no force flag), or, only
    when the remote could not be asked, leased against the head Keel last saw."""
    heads, skipped, lease = {}, [], lease or {}
    plans = [(entry, tree, *standing(tree, entry["branch"])) for entry, tree in trees]
    for entry, _, how, _ in plans:
        if how == "diverged":
            raise SandboxError(DIVERGED.format(repo=entry["repo"], branch=entry["branch"]))
    for entry, tree, how, there in plans:
        if how == "skip":
            skipped.append(entry["repo"])      # as the work adapter's: nothing to push from here
            continue
        expected = None if how == "forward" else lease.get(entry["repo"])
        leased = [f"--force-with-lease={entry['branch']}:{expected}"] if expected else []
        pushed = git(tree, "push", *leased, "origin", entry["branch"], timeout=180)
        if pushed.returncode != 0:
            raise SandboxError(f"git push of {entry['branch']} failed, so no reply was posted")
        heads[entry["repo"]] = git(tree, "rev-parse", "HEAD").stdout.strip()
    return heads, skipped


def post_replies(entries: list[dict], replies: list[dict]) -> tuple[list[str], list[dict]]:
    """Each reply once, as the pull request's author, under comment n for `c<n>`: the handles
    newly posted, and every reply now on the host as {handle, text}."""
    posted, sent = [], []
    for reply in replies:
        handle, text = str(reply.get("handle") or ""), str(reply.get("text") or "").strip()
        if not text:
            continue
        entry, local = target(entries, handle)
        parent = int(local[1:]) if re.fullmatch(r"c\d+", local) else None
        pr = sb_host.get(entry["repo"], entry["pr"])
        if not any(c["parent"] == parent and c["text"].strip() == text and c["author"] == pr["author"]
                   for c in pr["comments"]):
            sb_host.comment(entry["repo"], entry["pr"], text, parent=parent, author=pr["author"])
            posted.append(handle)
        sent.append({"handle": handle, "text": text})
    return posted, sent


def ship(card: dict, answer: dict) -> dict:
    """His Ship: handles and worktrees checked, then push, flip each draft, post the replies."""
    refuse_no_pr(card)
    entries = prs_of(card)
    if not entries:
        raise SandboxError(f"card {card['id']} has no pull request")
    replies = list(answer.get("replies") or [])
    for reply in replies:
        target(entries, str(reply.get("handle") or ""))
    heads, skipped = push_all(ship_trees(card, entries), answer.get("lease") if isinstance(answer.get("lease"), dict) else None)
    ready = [e["repo"] for e in entries if sb_host.get(e["repo"], e["pr"])["draft"]]
    for entry in entries:
        if entry["repo"] in ready:
            sb_host.set_draft(entry["repo"], entry["pr"], False)
    posted, sent = post_replies(entries, replies)
    return {"shipping": True, "shipped": True, "pr": int(entries[0]["pr"]), "pushed": heads,
            "skipped": skipped, "ready": ready, "posted": posted, "sent": sent}


# ----- a review card: his kept findings on a colleague's pull request -----

VERDICTS = {"approve": "approved", "changes": "changes_requested"}


def post_one(repo: str, number: int, bucket: dict, save, row: str, text: str, path=None, line=None) -> None:
    if row in bucket["comments"]:
        return
    said = next((c["id"] for c in sb_host.get(repo, number)["comments"]
                 if c["author"]["id"] == "me" and c["path"] == path and c["line"] == (int(line) if line else None)
                 and c["text"].strip() == text.strip()), None)
    bucket["comments"][row] = said if said is not None else sb_host.comment(repo, number, text, path, line)["id"]
    save()


def post_to(repo: str, number: int, bucket: dict, save, comments: list, summary: str | None, verdict: str) -> None:
    for one in comments:
        post_one(repo, number, bucket, save, one["row"], one["text"], one.get("path"), one.get("line"))
    if summary:
        post_one(repo, number, bucket, save, "summary", summary)
    if bucket.get("verdict") != verdict and verdict in VERDICTS:
        sb_host.review(repo, number, VERDICTS[verdict])
    bucket["verdict"] = verdict
    save()


def fresh(card: dict, review: dict) -> dict:
    posting = dict(option(card, "review_posting") or {})
    if posting.get("round") != review.get("round"):
        posting = {"round": review.get("round"), "comments": {}}
    posting["comments"] = dict(posting.get("comments") or {})
    return posting


def post_review(card: dict, review: dict) -> dict:
    """The kept findings inline, the summary, then the verdict; a feature card per member."""
    posting = fresh(card, review)
    save = lambda: KB.set_option(card["id"], "review_posting", posting)  # noqa: E731
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    if review.get("members"):
        buckets, done = posting.setdefault("members", {}), {}
        for one in review["members"]:
            bucket = buckets.setdefault(one["member"], {})
            bucket["comments"] = dict(bucket.get("comments") or {})
            post_to(one["repo"], int(one["pr"]), bucket, save, one.get("comments") or [],
                    one.get("pointer") or review.get("summary"), one.get("verdict") or "comment")
            done[one["member"]] = {"pr": int(one["pr"]), "repo": one["repo"], "verdict": bucket["verdict"],
                                   "summary": bucket["comments"].get("summary"),
                                   "comments": {r: c for r, c in bucket["comments"].items() if r != "summary"}}
        count = sum(len(one["comments"]) for one in done.values())
        posted = {"head": review.get("head"), "heads": review.get("heads") or {}, "round": review.get("round"),
                  "members": done, "verdict": review.get("verdict"), "severity": review.get("severity"),
                  "comments": {r: c for one in done.values() for r, c in one["comments"].items()},
                  "ledger": review.get("ledger") or [], "at": stamp}
        finish(card, posted, f"feature review posted: {count} inline comments across {len(done)} pull requests")
        return {"published": "review", "prs": [one["pr"] for one in done.values()], "comments": count,
                "verdict": review.get("verdict")}
    number = option(card, "pr")
    if not number:
        raise SandboxError(f"card {card['id']} names no pull request (options.pr)")
    post_to(primary_repo(card), int(number), posting, save, review.get("comments") or [],
            review.get("summary"), review.get("verdict") or "comment")
    ids = {row: cid for row, cid in posting["comments"].items() if row != "summary"}
    posted = {"head": review.get("head"), "round": review.get("round"), "comments": ids,
              "summary": posting["comments"].get("summary"), "verdict": posting["verdict"],
              "severity": review.get("severity"), "ledger": review.get("ledger") or [], "at": stamp}
    finish(card, posted, f"review posted on pull request #{number}: {len(ids)} inline "
                         f"comment{'s' if len(ids) != 1 else ''}, the summary, verdict {posted['verdict']}")
    return {"published": "review", "pr": int(number), "comments": len(ids), "verdict": posted["verdict"]}


def finish(card: dict, posted: dict, note: str) -> None:
    KB.set_option(card["id"], "review_posted", posted)
    KB.set_option(card["id"], "review_posting", None)
    KB.note(card["id"], note)
