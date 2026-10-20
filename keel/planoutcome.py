"""An outcome's boards and reading order (C33, c-602): the flow drawn at the BUILT head.

A plan's board is drawn before the code exists, often lean ("the full walk comes with the
outcome"), and c-573's outcome only re-embedded the plan's two boards as they were. So an
outcome that ships a change is held to what c-272's b-009 does by hand:

- at least one board embedded by id that was PUSHED after his plan approval (`approved_at`):
  a plan board redrawn to the built head, or the Code flow board the brief asks for;
- a NUMBERED reading order of `path:line`s under `## Why this shape` (C28's check, reused
  from `keel/planreview.py`);
- a WARNING per embedded board last pushed at or before that approval: it is the plan's
  drawing, carried over unchanged, and the page tags it "from the plan, not updated".

The rule is an error where the house can still fix it (`kb stage review` from building), and
a warning once the outcome is written (`written`: at review, shipping or done), so no card
already at his gate turns red and Bosun's approval facts are not refused by it. The cards
already written are what `bin/keel-outcome-boards` (`keel/outcomeboards.py`) backfills.

Board push times come from the board store (`boards.row_of`'s `pushed`), through the same
resolver the lint's C4 uses (`plangate.board_resolver`, `.pushed`). A time that cannot be
read (an older deck answering `board.show`) counts as fresh: the rule never refuses on what
it could not see.
"""

from __future__ import annotations

from datetime import datetime

from keel import planformat, planreview

RULE = "C33"
CARRIED = "from the plan, not updated"
# The stages at which an outcome was already written and sits at (or past) his gate.
WRITTEN = ("review", "shipping", "done")


def finding(text: str, block: str | None = None, level: str = "error") -> dict:
    return {"rule": RULE, "text": text, "block": block, "level": level}


def when(stamp) -> datetime | None:
    """An ISO stamp as an aware datetime (a naive one is local), or None."""
    try:
        moment = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.astimezone()


def approved_at(events) -> str | None:
    """When the plan was approved: the newest `approve` of the plan gate, else (a card that
    never had a plan gate) the FIRST move into building, the start of the build. Not the
    newest: a card sent back from review moves into building again, and its first round's
    boards were drawn at a built head too (c-602 review). None when neither happened."""
    events = [e for e in (events or []) if e.get("at")]
    approvals = [e for e in events if e["kind"] == "approve" and (e.get("data") or {}).get("gate") == "plan"]
    if approvals:
        return approvals[-1]["at"]
    builds = [e for e in events if e["kind"] == "stage" and (e.get("data") or {}).get("to") == "building"]
    return builds[0]["at"] if builds else None


# What an outcome's frontmatter may say about the change it records (c-602 review):
# `change: none` is a card with nothing to land (Approve closes it with the outcome as its
# record, `merging.NOTHING_TO_LAND`): no code was built, so there is no flow to redraw and C33
# does not hold it. `change: docs` is a docs-only change: no code to walk, so no Code flow
# board, but still the reading order (the pages to read, in order). Anything else is code.
CHANGE_KEY = "change"
NO_CHANGE, DOCS_ONLY = "none", "docs"


def change_of(doc: dict) -> str:
    return str((doc.get("meta") or {}).get(CHANGE_KEY) or "").strip().lower()


# What counts as documentation for `change: docs` (c-605 review): a README or CHANGELOG
# anywhere, `.md`/`.rst`/`.adoc` under a docs-like directory, and `.txt` only under one.
# Never a requirements.txt, a CMakeLists.txt, or a contract under etc/.
DOC_DIRS = ("docs", "doc", "documentation")
DOC_SUFFIXES = (".md", ".rst", ".adoc")
DOC_NAMES = ("readme", "changelog")


def is_doc(path: str) -> bool:
    parts = path.lower().split("/")
    stem = parts[-1].split(".")[0]
    if stem in DOC_NAMES:
        return True
    under_docs = any(part in DOC_DIRS for part in parts[:-1])
    return under_docs and parts[-1].endswith(DOC_SUFFIXES + (".txt",))


def claim_rules(change: str, changed, level: str) -> list[dict]:
    """The frontmatter's claim checked against the branch (c-605: a house wrote `change:
    none` over a real code change and dodged the Code flow board). `changed()` answers
    `branch_change`'s facts; a claim nothing could verify (no worktree read here, a repo
    whose base does not resolve) is NOT trusted. `none` holds only with no commit over the
    base in any repo; `docs` only when every changed file is documentation (`is_doc`)."""
    if change not in (NO_CHANGE, DOCS_ONLY) or changed is None:
        return []
    facts = changed()
    if not facts:
        said = "no worktree of the card could be read here, so the claim could not be verified"
        return [mismatch(change, said, level)]
    if facts.get("unverified"):
        said = "; ".join(facts["unverified"]) + ", so the claim could not be verified"
        return [mismatch(change, said, level)]
    files = sorted(set(facts.get("files") or []))
    if change == NO_CHANGE and facts.get("commits"):
        said = f"the branch has {facts['commits']} commit(s) over its base, changing {len(files)} file(s)"
    elif change == DOCS_ONLY and any(not is_doc(path) for path in files):
        code = [path for path in files if not is_doc(path)]
        said = f"the branch changes {len(code)} file(s) that are not docs ({', '.join(code[:3])})"
    else:
        return []
    return [mismatch(change, said + ": the claim did not match", level)]


def mismatch(change: str, said: str, level: str) -> dict:
    return finding(f"the outcome says `change: {change}`, but {said}. C33 holds it as a code "
                   f"change (a Code flow board pushed at the built head, and the reading "
                   f"order); correct the claim or the branch", level=level)


def branch_change(card: dict, first, base_for, remote: str | None = None) -> dict | None:
    """`{"commits": n, "files": [...], "unverified": [why]}` of the card's branch in every
    worktree of the card, `first` leading, each against its OWN base (`base_for(root)`, a
    branch name or None when it cannot be named); None when no worktree is here. A count
    over the base is taken again after one fetch of that base, so a stale remote-tracking
    ref never reads as the house's commits; nothing is fetched when the count is zero."""
    from keel.planlint import card_roots        # noqa: PLC0415 - planlint imports this module
    from keel.review import repo                # noqa: PLC0415 - git only when a claim is read
    own = repo.root_of(first) if first else None
    roots = card_roots(card, own)
    if not roots:
        return None
    out = {"commits": 0, "files": [], "unverified": []}
    for root in roots:
        name = base_for(root)
        count, ref = over_base(repo, root, name, remote)
        if count:
            repo.fetch_base(root, str(name).removeprefix(f"{remote or repo.DEFAULT_REMOTE}/"), remote)
            count, ref = over_base(repo, root, name, remote)
        if count is None:
            out["unverified"].append(f"the base of {root.name} ({name or 'none named'}) does not resolve")
            continue
        out["commits"] += count
        out["files"] += (repo.git(root, "diff", "--name-only", f"{ref}...HEAD") or "").split()
    return out


def over_base(repo, root, name, remote: str | None = None) -> tuple[int | None, str | None]:
    """Commits on HEAD that `name`'s head lacks, and the ref read; (None, None) unread."""
    ref = repo.base_ref(root, name, remote) if name else None
    count = repo.git(root, "rev-list", "--count", f"{ref}..HEAD") if ref else None
    if count is None or not count.strip().isdigit():
        return None, None
    return int(count.strip()), ref


def written(card: dict | None) -> bool:
    return bool(card) and card.get("stage") in WRITTEN


def pushed_of(board_of, ref: str) -> str | None:
    """The board's last push time, through the lint's board resolver, or None."""
    reader = getattr(board_of, "pushed", None)
    try:
        return reader(ref) if reader else None
    except Exception:  # noqa: BLE001 - a store that cannot say leaves the board unjudged
        return None


def carried(pushed, since) -> bool:
    """A board last pushed at or before the plan's approval: the plan's drawing, unchanged."""
    then, approved = when(pushed), when(since)
    return bool(then and approved and then <= approved)


def embedded(doc: dict) -> list[dict]:
    return [b for b in planformat.all_blocks(doc["blocks"]) if b["type"] == "board" and b.get("ref")]


def rules(doc: dict, board_of=None, since: str | None = None, level: str = "error",
          changed=None) -> list[dict]:
    """C33 for an outcome that ships a change: none for `change: none`, only the reading
    order for `change: docs`, each only when the branch agrees (`claim_rules`)."""
    change = change_of(doc)
    out = claim_rules(change, changed, level)
    if out:
        change = ""                          # the claim did not match: the whole of C33
    if change == NO_CHANGE:
        return []
    if change == DOCS_ONLY:
        return reading_order_rules(doc, level)
    boards = embedded(doc)
    stale = [b for b in boards if carried(pushed_of(board_of, b["ref"]), since)]
    for block in stale:
        out.append(finding(f"`{block['ref']}` is {CARRIED} since the plan was approved: push it again "
                           "at the built head (`keel board push --board <id>` redraws it)", block["id"], "warn"))
    if not boards:
        out.append(finding("the outcome embeds no board: redraw the plan's boards at the built head "
                           "and push ONE Code flow board, then embed each by id", level=level))
    elif len(stale) == len(boards) and since:
        out.append(finding("every board the outcome embeds is the plan's, unchanged: push at least one "
                           "after the build (a plan board redrawn, or the Code flow board)", level=level))
    return out + reading_order_rules(doc, level)


def reading_order_rules(doc: dict, level: str) -> list[dict]:
    if planreview.reading_order(planformat.section_blocks(doc, "why"), numbered=True):
        return []
    return [finding("`## Why this shape` gives no reading order: a numbered list of `path:line`s "
                    "(`### Read it in this order`), one per step of the Code flow board", level=level)]


def mark_carried(doc: dict, board_of, since: str | None) -> None:
    """The page's half: an embedded board carried over from the plan says so in its head."""
    if change_of(doc) in (NO_CHANGE, DOCS_ONLY):
        return
    for block in embedded(doc):
        if carried(pushed_of(board_of, block["ref"]), since):
            block["carried"] = CARRIED
