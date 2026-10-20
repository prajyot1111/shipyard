"""The review kind's rules (lane RC): what a review card's outcome must carry, C28 to C32.

A review card's house writes its outcome as `kind: review` (`docs/plan-format.md`), and his
Approve POSTS it: the kept findings as inline comments at their `path:line`, one summary,
the verdict (`keel/reviewround.py`). So the lint holds the shape that posting reads, at
`kb stage review`, before his gate opens on it:

- C28 an `## Orientation` first: what the change does, its code path as a board embedded by
  id, and a reading order that points at `path:line`s;
- C29 `## Findings` holds ONE ```finding block per surviving finding (lane FC,
  `keel/planfinding.py`): its severity, its `at: path:line`, its claim, the verifier's
  word, its drafted comment and its choice (post, edit or drop), and every finding that
  survived the verifier is a block (when the caller knows them); or `None: <why>`. The
  code shows on each finding, pulled at render, so there is no Snippets section;
- C30 exactly one `decision verdict`, its options comment, changes and approve (two or
  more), with `other: no`: the verdict is one of the three the code host takes;
- C31 on a re-review, no finding raises again one he posted or dropped on lines that did
  not change since (`keel/review/ledger.py` works out which lines those are);
- C32 on a FEATURE card (lane GRP, one story's pull requests reviewed together): every
  finding names its member (`member: cloud#4150`), its `path:line` resolves in THAT
  member's worktree when the caller knows them (`review["worktrees"]`), and there is
  exactly ONE verdict per member, `decision verdict-<repo>-<number>` (`verdict_id`), and no
  other decision. The members are the card's (`review["members"]`), else the frontmatter's.
  A TWIN (`review["twins"]`, {twin: member it follows}, c-559: the same change on another
  base, which prep did not hand the reviewer) is not a member here: a finding or a verdict
  on it is refused with the member to use instead, and the orientation must name each twin
  with the member it follows, both labels in one block.

THE OLD SHAPE (lane RC's: one `batch findings` of rows, a `copy comment <row>` per row, a
Snippets section) stays READABLE, because outcomes already at his gate were written in it
(c-480): `items` reads both, so his Approve posts either. A NEW outcome in it is refused
(C29); `legacy=True`, which the page passes for a card already at its gate, makes that a
warning, so the page does not call an outcome broken that was right when it was written.

`review` is what the caller knows beyond the file (`keel/review/ledger.py`): `{"reviewed":
bool | None, "surviving": [finding ids], "ledger": [{"id", "path", "line", "choice"}],
"members": [labels], "worktrees": {label: path}, "twins": {label: label}}`, with each ledger line already moved to
where it now sits and the changed ones left out. Without it the checks that need it are
skipped, never guessed.
"""

from __future__ import annotations

import re

from keel import planformat
from keel.planinline import plain, walk_refs

FINDING_CHOICES = ("post", "edit", "drop")
VERDICT_ID = "verdict"
VERDICTS = ("comment", "changes", "approve")
COMMENT_PREFIX = "comment "
ORDER = ("orientation", "findings", "verdict")
OLD_SHAPE = ("`## Findings` is one ```finding block per finding (severity, `at: path:line`, claim, "
             "verifier, `comment:`, `choice:`); the batch with `copy comment` blocks and a Snippets "
             "section is the old shape, kept only for outcomes written before it")


def finding(rule: str, text: str, block: str | None = None, level: str = "error") -> dict:
    return {"rule": rule, "text": text, "block": block, "level": level}


def row_id(finding_id: str) -> str:
    """A finding id as the outcome carries it: `r1.F1` is `r1-f1` (an id has no dot, and
    the parser reads keys in lower case)."""
    return str(finding_id).replace(".", "-").lower()


def rules(doc: dict, review: dict | None = None, legacy: bool = False) -> list[dict]:
    """Every C28 to C32 finding for one parsed review."""
    out = orientation_rules(doc) + order_rules(doc) + findings_rules(doc, review, legacy)
    if review is not None and review.get("reviewed") is False:
        out.append(finding("C29", "Keel's review core has not reviewed this HEAD: run the "
                                  "reviewer (and the verifier when it finds anything) first"))
    members = members_of(doc, review)
    if members:
        paired = (review or {}).get("twins") or {}
        out += member_rules(doc, members, (review or {}).get("worktrees"), paired) \
            + feature_verdict_rules(doc, members, paired) + twin_rules(doc, paired)
    else:
        out += verdict_rules(doc)
    if review is not None:
        out += ledger_rules(doc, review.get("ledger") or [], members)
    return out


# ----- the findings, in either shape -----

def finding_blocks(doc: dict) -> list[dict]:
    return [b for b in planformat.all_blocks(doc["blocks"]) if b["type"] == "finding"]


def findings_batch(doc: dict) -> list[dict]:
    return [b for b in planformat.section_blocks(doc, "findings") if b["type"] == "batch"]


def is_old(doc: dict) -> bool:
    """Written in lane RC's shape: a findings batch and no finding blocks."""
    return bool(findings_batch(doc)) and not finding_blocks(doc)


def items(doc: dict, members: list[str] | None = None) -> list[dict]:
    """Every finding as one record, whatever shape it was written in: `{id, path, line,
    end, member, claim, comment, rec, severity, mark}`, `mark` being the (block, row) his
    pick on it is stored under (`keel/planstate.py`)."""
    if not is_old(doc):
        return [item_of(b) for b in finding_blocks(doc)]
    batch = findings_batch(doc)[0]
    words = drafts(doc)
    out = []
    for row in batch.get("rows", []):
        anchor = anchor_of(row)
        text = plain(row.get("text") or [])
        claim = " ".join(text.replace(anchor["v"], "").split()) if anchor else text
        out.append({"id": row["id"], "path": anchor and anchor["path"], "line": anchor and anchor["start"],
                    "end": anchor and anchor["end"], "member": member_of(row, members or []),
                    "claim": claim, "comment": words.get(row["id"], ""), "rec": row.get("rec"),
                    "severity": None, "mark": (batch["id"], row["id"])})
    return out


def item_of(block: dict) -> dict:
    return {"id": block["id"], "path": block.get("path"), "line": block.get("start"), "end": block.get("end"),
            "member": block.get("member"), "claim": plain(block.get("claim") or []),
            "comment": str(block.get("comment") or "").strip(), "rec": block.get("rec"),
            "severity": block.get("severity"), "mark": (block["id"], block["id"])}


def drafts(doc: dict) -> dict:
    """Each `copy comment <row>` block's words, by row id (the old shape)."""
    out = {}
    for block in planformat.all_blocks(doc["blocks"]):
        title = str(block.get("title") or "")
        if block.get("type") == "copy" and title.startswith(COMMENT_PREFIX):
            out[title[len(COMMENT_PREFIX):].strip().lower()] = str(block.get("text") or "").strip()
    return out


def anchor_of(row: dict) -> dict | None:
    """The first `path:line` an old-shape row names: where its comment is posted."""
    return next((ref for ref in walk_refs(row.get("text") or []) if ref.get("kind") == "path"), None)


# ----- C32, a feature card (lane GRP) -----

def verdict_id(label: str) -> str:
    """A member's verdict decision id: `cloud#4150` is `verdict-cloud-4150`."""
    return VERDICT_ID + "-" + re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")


def members_of(doc: dict, review: dict | None) -> list[str]:
    """The feature's member labels: the card's, else the frontmatter's; [] for one pull request."""
    found = (review or {}).get("members")
    if not found:
        found = [one.strip() for one in str((doc.get("meta") or {}).get("members") or "").split(",")]
    return [one for one in found if one]


def member_of(row: dict, members: list[str]) -> str | None:
    """The member an old-shape row names: the first label in its words."""
    words = plain(row.get("text") or [])
    hits = [(words.find(label), label) for label in members if label in words]
    return min(hits)[1] if hits else None


def member_rules(doc: dict, members: list[str], worktrees: dict | None = None,
                 paired: dict | None = None) -> list[dict]:
    out = []
    for one in items(doc, members):
        if one["member"] in (paired or {}):
            out.append(finding("C32", f"finding {one['id']} names {one['member']}, the twin of "
                                      f"{paired[one['member']]}: a twin is not reviewed, so put it on "
                                      f"{paired[one['member']]} or drop it", one["mark"][0]))
        elif one["member"] not in members:
            said = f"names {one['member']}, which is not a member" if one["member"] else "names no member"
            out.append(finding("C32", f"finding {one['id']} {said}: say which member it is posted on "
                                      f"with `member:` ({', '.join(members)})", one["mark"][0]))
        elif worktrees and one["path"] and one["member"] in worktrees and not is_old(doc):
            why = resolve_in(worktrees[one["member"]], one["path"], one["line"], one["end"])
            if why:
                out.append(finding("C32", f"finding {one['id']}'s `{one['path']}:{one['line']}` does not resolve "
                                          f"in {one['member']}'s worktree ({why}): is it on the other member?",
                                   one["mark"][0]))
    return out


def twin_rules(doc: dict, paired: dict) -> list[dict]:
    """Each twin named in the orientation with the member it follows, in one block."""
    said = [planformat.text_of(b) for b in planformat.section_blocks(doc, "orientation")]
    return [finding("C32", f"the orientation does not name {twin} as the twin of {primary}: say, in one "
                           f"line, `{twin} is the twin of {primary}: the same change, reviewed there`")
            for twin, primary in paired.items() if not any(twin in text and primary in text for text in said)]


def resolve_in(tree: str, path: str, start: int, end: int | None) -> str | None:
    from keel.planlint import GitResolver     # the lint owns the git read; imported late, it imports us
    return GitResolver(tree)(path, int(start), int(end or start))


def feature_verdict_rules(doc: dict, members: list[str], paired: dict | None = None) -> list[dict]:
    """ONE `decision verdict-<repo>-<number>` per member, and no other decision."""
    decisions = [b for b in planformat.all_blocks(doc["blocks"]) if b["type"] == "decision"]
    wanted = {verdict_id(label): label for label in members}
    twins = {verdict_id(label): primary for label, primary in (paired or {}).items()}
    out = []
    for label in members:
        count = sum(1 for b in decisions if b.get("id") == verdict_id(label))
        if count != 1:
            said = "has no verdict" if not count else f"has {count} verdicts"
            out.append(finding("C32", f"{label} {said}: a feature review has exactly one "
                                      f"```decision {verdict_id(label)} per member"))
    for block in decisions:
        if block.get("id") in twins:
            out.append(finding("C32", f"```decision {block.get('id')} is a twin's verdict: a twin takes "
                                      f"{twins[block['id']]}'s verdict, so take this one out", block["id"]))
        elif block.get("id") not in wanted:
            out.append(finding("C32", f"```decision {block.get('id')} is not a member's verdict: a feature "
                                      f"review's decisions are {', '.join(sorted(wanted))}", block["id"]))
        else:
            out += verdict_shape(block)
    return out


def section_names(doc: dict) -> list[str]:
    return [s["name"] for s in doc["sections"] if s["name"]]


def order_rules(doc: dict) -> list[dict]:
    names = [n for n in section_names(doc) if n in ORDER]
    if names and names[0] != "orientation" and "orientation" in names:
        return [finding("C28", "the orientation comes first: `## Orientation` before the findings and the verdict")]
    return []


# ----- C28 -----

def orientation_rules(doc: dict) -> list[dict]:
    if "orientation" not in section_names(doc):
        return [finding("C28", "a review opens with `## Orientation`: what the change does, its "
                               "code path as a board embedded by id, and a reading order of `path:line`s")]
    blocks = planformat.section_blocks(doc, "orientation")
    out = []
    if not any(b["type"] == "paragraph" for b in blocks):
        out.append(finding("C28", "the orientation says what the change does, in a paragraph"))
    if not any(b["type"] == "board" and b.get("ref") for b in blocks):
        out.append(finding("C28", "the orientation embeds the change's code path as a board BY ID "
                                  "(`keel board push --new --card <id>`, then a ```board block with the id)"))
    if not reading_order(blocks):
        out.append(finding("C28", "the orientation gives a reading order: a list of `path:line`s "
                                  "in the order to read them"))
    return out


def reading_order(blocks: list[dict], numbered: bool = False) -> bool:
    """A list of `path:line`s among these blocks: a review's orientation (C28), and with
    `numbered` an outcome's "Read it in this order" under Why this shape (C33, c-602)."""
    return any(ref.get("kind") == "path" for b in blocks
               if b["type"] == "list" and (b.get("ordered") or not numbered) for ref in refs(b))


def refs(block: dict):
    from keel.planlint import refs_of      # the lint owns the walk; imported late, it imports us
    yield from refs_of(block)


# ----- C29 -----

def findings_rules(doc: dict, review: dict | None, legacy: bool = False) -> list[dict]:
    if "findings" not in section_names(doc):
        return [finding("C29", "a review has `## Findings`: one ```finding block per surviving "
                               "finding, or `None:` and why")]
    if is_old(doc):
        return [finding("C29", OLD_SHAPE, findings_batch(doc)[0]["id"], "warn" if legacy else "error")] \
            + (old_rules(doc, review) if legacy else [])
    blocks = finding_blocks(doc)
    if not blocks:
        section = planformat.section_blocks(doc, "findings")
        said = plain(section[0].get("text") or []) if section and section[0]["type"] == "paragraph" else ""
        if not said.lower().startswith("none:") or len(said.split()) < 3:
            return [finding("C29", "`## Findings` holds one ```finding block per finding, or says `None:` and why")]
    out = []
    if "snippets" in section_names(doc):
        out.append(finding("C29", "a finding shows its own code, pulled from the worktree when the page "
                                  "draws it: take the `## Snippets` section out"))
    return out + surviving_rules([b["id"] for b in blocks], review)


def old_rules(doc: dict, review: dict | None) -> list[dict]:
    """The old shape's own checks, for an outcome already written in it (lane RC's C29)."""
    batches = findings_batch(doc)
    out = []
    if len(batches) > 1:
        out.append(finding("C29", "`## Findings` holds ONE batch; put every finding in it", batches[1]["id"]))
    block = batches[0]
    if sorted(block.get("choices") or []) != sorted(FINDING_CHOICES):
        out.append(finding("C29", "a finding's choices are post, edit and drop", block["id"]))
    for one in items(doc):
        if one["path"] is None:
            out.append(finding("C29", f"finding {one['id']} names no `path:line` to post its comment at", block["id"]))
        if not one["comment"]:
            out.append(finding("C29", f"finding {one['id']} has no drafted comment: a ```copy comment "
                                      f"{one['id']} block with the words to post", block["id"]))
    return out + surviving_rules([row["id"] for row in block.get("rows", [])], review)


def surviving_rules(have: list[str], review: dict | None) -> list[dict]:
    if not review or not review.get("surviving"):
        return []
    missing = [one for one in review["surviving"] if row_id(one) not in set(have)]
    return [finding("C29", f"finding {row_id(one)} survived the verifier and is not on the outcome: every "
                           f"surviving finding is the user's to post, edit or drop") for one in missing]


# ----- C30 -----

def verdict_rules(doc: dict) -> list[dict]:
    decisions = [b for b in planformat.all_blocks(doc["blocks"]) if b["type"] == "decision"]
    verdicts = [b for b in decisions if b.get("id") == VERDICT_ID]
    others = [b for b in decisions if b.get("id") != VERDICT_ID]
    if len(verdicts) != 1 or others:
        return [finding("C30", "a review has exactly one decision, ```decision verdict (comment, "
                               "changes or approve); the findings are the finding blocks")]
    return verdict_shape(verdicts[0])


def verdict_shape(block: dict) -> list[dict]:
    """One verdict decision's options and `other: no` (C30)."""
    ids = [o["id"] for o in block.get("options", [])]
    wrong = [i for i in ids if i not in VERDICTS]
    out = []
    if wrong:
        out.append(finding("C30", f"the verdict's options are comment, changes and approve, not "
                                  f"{', '.join(wrong)}", block["id"]))
    if block.get("other") is not False:
        out.append(finding("C30", "the verdict says `other: no`: the code host takes only these three",
                           block["id"]))
    return out


# ----- C31 -----

def ledger_rules(doc: dict, ledger: list[dict], members: list[str] | None = None) -> list[dict]:
    """A finding at the same place as one he already posted or dropped, on lines that did
    not change since: the reviewer raised it again. On a feature card the place is the
    member too: the same path and line in the other repo is another place."""
    places = {(one.get("member") if members else None, str(one.get("path")), int(one.get("line") or 0)): one
              for one in ledger}
    out = []
    for one in items(doc, members):
        if one["path"] is None:
            continue
        old = places.get((one["member"] if members else None, one["path"], int(one["line"])))
        if old is not None:
            out.append(finding("C31", f"finding {one['id']} is {old.get('id')} again, which the user "
                                      f"{'posted' if old.get('choice') != 'drop' else 'dropped'} "
                                      f"last round, and `{one['path']}:{one['line']}` has not "
                                      f"changed since: take it out", one["mark"][0]))
    return out
