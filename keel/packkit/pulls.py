"""`pr`, `publishable` and `publish`: a card's changes on the host, one per repo.

- `pr <id> --draft` opens a DRAFT in every repo whose branch is on the remote (the title is
  the card's; the body is the repo's ```copy block under the body section in the card's
  record, else the first, else the card's title and brief), records each and prints the
  addresses. `pr <id> --body` puts the record's body on each. `pr <id> --ready` is refused
  (r1.F2): only `publish` marks a change ready, inside Approve outcome.
- `publishable` holds the card at `kb stage review` until every repo's branch is on the
  remote with its head and a change is open from it.
- `publish` (Approve outcome) marks every draft ready, writes one note and answers
  `"shipping": true`, so Keel watches the change until it is merged on the host. With
  `--answer` it is Ship on a card at shipping (`ship.py`), or, on a review card (c-730), the
  review you kept, posted on someone else's change (`review.post`).

Nothing here pushes, merges or closes. A house pushes its own card branch; a merge is the
user's, on the host.
"""

import re

from keel.packkit import card as gc
from keel.packkit import pack, review, shared, ship
from keel.packkit.errors import HostError
from keel.packkit.layer import UNKNOWN

REMOTE_SECONDS = 45

# ----- the title and the body -----

COPY_OPEN = re.compile(r"^(?P<ticks>`{3,}|~{3,})\s*copy\b(?P<title>[^\n]*)$")
PLACEHOLDER = re.compile(r"^_.*_$")


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
    """What the house wrote under the body section (`## <short> body`): the ```copy block
    whose title names `repo`, else the first, else the section's own text. None while it is
    empty or one italic placeholder line."""
    heading = re.escape(pack.words().short)
    match = re.search(rf"^##\s*{heading} body[^\n]*\n(.*)\Z", text, re.S | re.M | re.I)
    if not match:
        return None
    blocks = copy_blocks(match.group(1))
    body = blocks[0][1] if blocks else match.group(1).strip()
    if blocks and repo:
        word = re.compile(rf"(?<![\w-]){re.escape(repo)}(?![\w-])", re.I)
        body = next((text for title, text in blocks if word.search(title)), body)
    if not body or ("\n" not in body and PLACEHOLDER.match(body)):
        return None
    return body


def default_body(card: dict) -> str:
    parts = [(card.get("brief") or "").strip(), f"Shipyard card {card['id']}."]
    return "\n\n".join(part for part in parts if part) + "\n"


def body_for(card: dict, repo: str) -> str:
    return body_section(gc.context_text(card["id"]), repo) or default_body(card)


def title_for(card: dict) -> str:
    return (card.get("title") or "").strip() or f"Shipyard card {card['id']}"


# ----- the branch on the remote -----

def remote_head(card: dict, key: str, branch: str) -> str | None:
    """The commit the remote has at `branch`, or None when it has no such branch."""
    return gc.remote_head(card, key, branch, timeout=REMOTE_SECONDS)


def head_pushed(card: dict, key: str, branch: str, there: str) -> bool:
    """True when the remote's commit holds the local branch's tip (or there is none here)."""
    repo = gc.repo_path(card, key)
    local = gc.git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").stdout.strip()
    if not local or local == there:
        return True
    if gc.git(repo, "cat-file", "-e", there).returncode != 0:
        gc.fetch(repo, gc.remote_of(card), branch, timeout=REMOTE_SECONDS)
    return gc.git(repo, "merge-base", "--is-ancestor", local, there).returncode == 0


# ----- open and ready: one change per repo -----

def open_drafts(card: dict) -> dict:
    """The card's draft in each of its repos, opened now or found open already, each
    recorded: `{"opened": [change + repo], "skipped": [{repo, why}]}`. A repo whose branch
    is not on the remote is skipped and said; a card with none opened is refused."""
    gc.refuse_no_pr(card)
    keys, opened, skipped = gc.repos_of(card) or [gc.primary_repo(card)], [], []
    for repo in keys:
        found, card, why = open_one(card, repo)
        if found is None:
            if len(keys) == 1:
                raise HostError(why)
            skipped.append({"repo": repo, "why": why})
            continue
        opened.append(dict(found, repo=repo))
    if not opened:
        raise HostError("no branch is on the remote yet in " + ", ".join(one["repo"] for one in skipped)
                        + ": push each first")
    return {"opened": opened, "skipped": skipped}


def open_one(card: dict, repo: str) -> tuple[dict | None, dict, str]:
    """One repo's change (the recorded one, one found open on its branch, or a new draft)
    and the card after recording it; or None and why."""
    host, layer = gc.host_repo(card, repo), pack.layer()
    branch = gc.branch_in(card, repo)
    shared.refuse(card, repo, branch)
    number = gc.recorded_pr(card, repo)
    if number:
        return layer.get(host, number), card, ""
    found = layer.find_open(host, branch)
    if found is None:
        if remote_head(card, repo, branch) is None:
            return None, card, f"branch {branch} is not on the remote yet: push it first"
        found = layer.open_pr(host, title_for(card), branch, shared.base_in(card, repo, writing=True),
                              body_for(card, repo), draft=True, cwd=gc.repo_path(card, repo))
    card = gc.record_pr(card, repo, found["id"])
    named = f"{repo} " if len(gc.repos_of(card)) > 1 else ""
    gc.KB.note(card["id"], f"{named}{'draft ' if found['draft'] else ''}{pack.words().change} "
                           f"#{found['id']}: {found['url']}")
    return found, card, ""


def found_prs(card: dict, what: str) -> tuple[list[tuple], dict]:
    """(repo, Repo, number) of the card's change in EVERY repo, found before anything is
    changed, so one that is missing refuses the whole; and the card after recording."""
    gc.refuse_no_pr(card)
    keys, found = gc.repos_of(card) or [gc.primary_repo(card)], []
    for repo in keys:
        host, number = gc.host_repo(card, repo), gc.recorded_pr(card, repo)
        if not number:
            hit = pack.layer().find_open(host, gc.branch_in(card, repo))
            if hit is None:
                where = f" in {repo}" if len(keys) > 1 else ""
                raise HostError(f"card {card['id']} has no {pack.words().change}{where} to {what}")
            number = hit["id"]
            card = gc.record_pr(card, repo, number)
        found.append((repo, host, int(number)))
    return found, card


def make_ready(card: dict) -> list[dict]:
    """Every repo's change marked ready for review, each as it then stands with its repo,
    primary first. One already ready is left alone, so a retry is safe."""
    found, card = found_prs(card, "mark ready")
    layer, w = pack.layer(), pack.words()
    read = [(repo, host, number, layer.get(host, number)) for repo, host, number in found]
    for _, host, number, now in read:        # every one is read before any is marked
        if now["state"] == UNKNOWN:
            raise gc.unknown_state(host, number)
        if now["state"] == "declined":
            raise HostError(f"{w.change} #{number} of {host} was closed {w.on} without "
                            f"being merged, so there is nothing to mark ready")
    out = []
    for repo, host, number, now in read:
        if now["state"] == "open" and now["draft"]:
            layer.set_ready(host, number)
            now = dict(now, draft=False)
        out.append(dict(now, repo=repo))
    return out


def refresh_bodies(card: dict) -> list[dict]:
    """The record's body on the card's change in every repo; refused while the house has
    written none, so a default body is never put over a real one."""
    text = gc.context_text(card["id"])
    found, card = found_prs(card, "put a body on")
    bodies = {repo: body_section(text, repo) for repo, _, _ in found}
    if not all(bodies.values()):
        short = pack.words().short
        raise HostError(f"card {card['id']} has no {short} body in context.md yet: write the "
                        f"`## {short} body` section first")
    for repo, host, number in found:
        pack.layer().set_body(host, number, bodies[repo])
    return [{"repo": repo, "id": number, "url": pack.host().pr_url(host, number)} for repo, host, number in found]


# ----- publishable -----

def missing(card: dict) -> str | None:
    """What stops this card's outcome being published, in one line, or None. Live: the
    remote and the host are asked for each of the card's repos in turn."""
    if not gc.code_card(card):
        return None
    keys, w = gc.repos_of(card), pack.words()
    for key in keys:
        branch, where = gc.branch_in(card, key), f" in {key}" if len(keys) > 1 else ""
        push = f"`git push -u {gc.remote_of(card)} {branch}`"
        there = remote_head(card, key, branch)
        if there is None:
            return (f"{card['id']} is not publishable: branch {branch} is not on the remote{where}. "
                    f"Push it ({push}), open the draft (`pr {card['id']} --draft`), then stage review.")
        if not head_pushed(card, key, branch, there):
            return (f"{card['id']} is not publishable: {branch}{where} has commits the remote does "
                    f"not. Push again ({push}), then stage review.")
        if gc.recorded_pr(card, key):
            continue
        found = pack.layer().find_open(gc.host_repo(card, key), branch)
        if found is None:
            return (f"{card['id']} is not publishable: no {w.change} is open from {branch}{where}. "
                    f"Open it (`pr {card['id']} --draft`), then stage review.")
        card = gc.record_pr(card, key, found["id"])
    return None


def unpublished(card: dict) -> str | None:
    """The deck's line for a code card at the outcome gate lacking a change: card fields
    only, so it reads no clone and asks the host nothing."""
    if card.get("stage") != "review" or not gc.code_card(card):
        return None
    w = pack.words()
    have = {entry["repo"] for entry in gc.prs_of(card)}
    if not have:
        return (f"Not publishable: no {w.change} is open for it, and Approve only marks a draft "
                f"ready. Send back so its house pushes the branch and opens the draft.")
    lacking = [key for key in gc.repos_of(card) if key not in have]
    if not lacking:
        return None
    return (f"Not publishable: no {w.change} is recorded for {', '.join(lacking)}, and Approve "
            f"marks every repo's draft ready. Send back so its house opens it there.")


# ----- publish -----

SHIP_ONLY = ("{card} is at shipping: only your Ship pushes its commits or writes to its {change}. "
             "Commit, record `kb verdict`, and end your turn.")


TAP_ONLY = ("{card}'s `publish` runs only inside your Approve outcome or your Ship, which Shipyard marks on "
            "the card for the length of the tap: a house never runs it. Finish with `kb stage {card} review` "
            "and end your turn.")
# The tap's nonce, as Keel hands it to `publish` (`keel/adapters.py` NONCE_ENV, c-738 r1.F3).
NONCE_ENV = "KEEL_PUBLISH_NONCE"


# r2.F3: a tap's marker is honoured this long after the board wrote it (`at`), comfortably
# longer than a real publish. A `kb` killed mid-tap never clears its marker, so one older than
# this is a leftover, and its nonce (which an orphaned publish may still hold) opens nothing.
TAP_SECONDS = 15 * 60
SKEW_SECONDS = 60      # a marker stamped a little ahead of this clock is still the tap's


def clock():
    """This process's clock, the seam a test pins."""
    from datetime import datetime, timezone  # noqa: PLC0415 - only publish asks
    return datetime.now(timezone.utc)


def fresh(marker) -> bool:
    """Whether a tap's marker was written within `TAP_SECONDS`, by its `at`."""
    from datetime import datetime  # noqa: PLC0415
    try:
        at = datetime.fromisoformat(str(marker.get("at")))
        age = (clock() - at).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return False
    return -SKEW_SECONDS <= age <= TAP_SECONDS


def take_nonce() -> str:
    """The nonce Keel handed this run, read once and taken out of this process's environment
    before any child runs (r2.F2): no git, host tool or `kb` this verb starts is handed it."""
    import os  # noqa: PLC0415 - only publish asks
    return os.environ.pop(NONCE_ENV, "") or ""


def in_tap(card: dict, nonce: str) -> bool:
    """Whether this run is inside the user's tap: the nonce Keel handed matches the digest the board
    keeps on the card (`options.publishing`, `Board.mark_publishing`). A marker alone is not
    enough, so a house that runs `publish` while the user's tap is open is refused too."""
    import hmac  # noqa: PLC0415 - only publish asks
    from keel.board import nonce_digest  # noqa: PLC0415 - the board's own digest, Keel on the path
    marker = gc.option(card, "publishing")
    if not fresh(marker):
        return False
    digest = marker.get("digest") if isinstance(marker, dict) else None
    return bool(nonce and isinstance(digest, str) and hmac.compare_digest(digest, nonce_digest(nonce)))


def refuse_unless_shipping_tap(card: dict, verb: str, nonce: str = "") -> None:
    """`publish` runs only inside the user's tap (Approve outcome, Ship), at every stage (c-738
    r1.F3), with the tap's `nonce`; at shipping `pr` never runs."""
    if verb == "publish" and in_tap(card, nonce):
        return
    if card.get("stage") == "shipping":
        raise HostError(SHIP_ONLY.format(card=card.get("id"), change=pack.words().change))
    if verb == "publish":
        raise HostError(TAP_ONLY.format(card=card.get("id")))


def publish(card: dict, answer: dict | None = None, nonce: str | None = None) -> dict:
    """`nonce`: the tap's, as the verb took it (`take_nonce`); taken here when not handed."""
    nonce = take_nonce() if nonce is None else nonce
    refuse_unless_shipping_tap(card, "publish", nonce)  # first, for every kind of card (c-738 r1.F3)
    answer, w = answer or {}, pack.words()
    if gc.is_tracking(card):
        gc.KB.note(card["id"], f"tracking card closed: every slice published its own {w.change}")
        return {"published": "nothing", "kind": "tracking"}
    if gc.is_research(card):
        gc.KB.note(card["id"], "research outcome accepted: its record is the outcome; nothing was published")
        return {"published": "nothing", "kind": "research"}
    if gc.is_review(card):
        # c-730: Approve outcome on a review card posts the review you kept, and nothing else
        if not isinstance(answer.get("review"), dict):
            raise HostError(f"{card['id']} is a review card: Approve posts the review you kept, and none was handed")
        return review.post(card, answer["review"])
    if "review" in answer:
        raise HostError(f"{card['id']} is not a review card, so it posts no review")
    if "ship" in answer:
        return ship.ship(card, answer)
    ready = make_ready(card)
    result = {"pr": ready[0]["id"], "url": ready[0]["url"], "draft": ready[0]["draft"], "shipping": True}
    heads = {one["repo"]: one["head"] for one in ready if one.get("head")}
    if heads:
        result["heads"] = heads
    if len(ready) > 1:
        result["prs"] = [{"repo": one["repo"], "pr": one["id"], "url": one["url"], "draft": one["draft"]}
                         for one in ready]
    gc.KB.note(card["id"], publish_note(result))
    return result


def publish_note(result: dict) -> str:
    w = pack.words()
    if result.get("prs"):
        return f"published: {w.changes} " + ", ".join(
            f"{one['repo']} #{one['pr']} ({one['url']})" for one in result["prs"]) + " ready for review"
    return f"published: {w.change} #{result['pr']} ready for review ({result['url']})"
