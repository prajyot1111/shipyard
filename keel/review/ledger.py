"""What a review card's lint knows beyond its file (lane RC): the core's rounds and the
last round's ledger, with each ledger line moved to where it now sits.

`context` answers `planlint.lint`'s `review` argument for a review card at `kb stage
review`, on the house's machine:

- `reviewed`: the core reviewed the worktree's HEAD, a complete round (the verifier went
  through its findings, or there were none) recorded by the harness in
  `review-findings.json`. None when git cannot say, which never refuses.
- `surviving`: that round's findings the verifier did not refute, each his to post, edit
  or drop.
- `ledger`: what he posted and dropped last time (`options.review_posted.ledger`, written by
  his Approve), each at the line it sits on NOW, and only those whose lines did not change
  since the head he reviewed (`git diff -U0 <head>..HEAD`). A finding raised at one of
  those places is raised again, which C31 refuses.
"""

from __future__ import annotations

import re
from pathlib import Path

from keel.review import findings, repo, stamp, twins

POSTED_OPTION = "review_posted"
MEMBERS_OPTION = "review_members"
TREES_OPTION = "review_worktrees"
CARRIED_OPTION = "review_carried"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
FILE = re.compile(r"^\+\+\+ b/(.+)$")
OLD_FILE = re.compile(r"^--- a/(.+)$")


def hunks(diff: str) -> dict[str, list[tuple[int, int, int, int]]]:
    """Each file's hunks as (old start, old count, new start, new count), by old path."""
    out: dict[str, list] = {}
    current = None
    for line in diff.splitlines():
        old = OLD_FILE.match(line)
        if old:
            current = old.group(1)
            continue
        if line.startswith("--- /dev/null"):
            current = None
            continue
        match = HUNK.match(line)
        if match and current:
            a, b, c, d = match.groups()
            out.setdefault(current, []).append((int(a), int(b if b is not None else 1),
                                                int(c), int(d if d is not None else 1)))
    return out


def moved(line: int, file_hunks: list[tuple[int, int, int, int]]) -> int | None:
    """Where an old line sits now, or None when the change touched it."""
    shift = 0
    for a, b, c, d in file_hunks:
        if b and a <= line <= a + b - 1:
            return None
        before = (a + b - 1 < line) if b else (a < line)
        if before:
            shift += d - b
    return line + shift


def carried(ledger: list[dict], diff: str) -> list[dict]:
    """The ledger entries whose lines did not change, each at its line now."""
    by_file = hunks(diff)
    out = []
    for one in ledger:
        path, line = one.get("path"), one.get("line")
        if not path or not line:
            continue
        now = moved(int(line), by_file.get(path, []))
        if now is not None:
            out.append(dict(one, line=now))
    return out


def newest_complete(card_dir: Path) -> dict | None:
    rounds = [r for r in stamp.read_rounds(card_dir) if r.get("complete") and not r.get("unparsed")]
    return rounds[-1] if rounds else None


def context(card: dict, card_dir: Path, cwd) -> dict:
    """The lint's `review` argument for a review card (see the module). A feature card's
    (lane GRP) also carries its `members`, and its ledger is each member's lines moved in
    that member's own worktree."""
    head = repo.head_of(cwd) if cwd else None
    last = newest_complete(card_dir)
    options = card.get("options") or {}
    # a twin (keel/review/twins.py) is reviewed through the member it follows: no finding
    # and no verdict of its own, and the orientation names it with that member
    paired = twins.followed(card_dir)
    members = [m["label"] for m in options.get(MEMBERS_OPTION) or [] if m.get("label") and m["label"] not in paired]
    out = {"reviewed": None if head is None else bool(last and last.get("head") == head),
           "surviving": [one["id"] for one in findings.surviving((last or {}).get("findings") or [])],
           "ledger": [], "members": members}
    posted = options.get(POSTED_OPTION) or {}
    if members:
        out["ledger"] = feature_ledger(options, posted)
        out["twins"] = {label: primary for label, primary in paired.items() if primary in members}
        # C32 (lane FC): each finding's path:line resolves in its own member's worktree
        out["worktrees"] = {k: v for k, v in (options.get(TREES_OPTION) or {}).items() if k in members}
        return out
    if posted.get("head") and posted.get("ledger") and head:
        diff = repo.git(cwd, "diff", "-U0", f"{posted['head']}..HEAD")
        out["ledger"] = carried(posted["ledger"], diff) if diff is not None else list(posted["ledger"])
    return out


def feature_ledger(options: dict, posted: dict) -> list[dict]:
    """A feature card's ledger (lane GRP): what he answered on it (`review_posted`, each
    line naming its member, the heads by member in `heads`) and on a member's own single
    review before it was folded in (`review_carried`), each line moved through the diff
    since that head in its member's worktree; a member with no worktree keeps its lines."""
    trees = options.get(TREES_OPTION) or {}
    batches: dict[tuple, list] = {}
    for one in posted.get("ledger") or []:
        member = one.get("member")
        batches.setdefault((member, (posted.get("heads") or {}).get(member)), []).append(one)
    for one in options.get(CARRIED_OPTION) or []:
        batches.setdefault((one.get("member"), one.get("head")), []).extend(one.get("ledger") or [])
    out = []
    for (member, since), lines in batches.items():
        tree = trees.get(member)
        diff = repo.git(tree, "diff", "-U0", f"{since}..HEAD") if tree and since else None
        out += carried(lines, diff) if diff is not None else list(lines)
    return out
