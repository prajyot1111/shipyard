"""The authoring contract, as a lint a house runs and a stage refuses on.

The lavish skill's discipline lived in prose the house had to remember to load, and the one
time it was not loaded the plans stopped asking questions (c-208, c-212). So the contract's
enforceable rules are a MECHANISM here: `kb lint` prints the findings, and `kb stage
planning --plan <file>` refuses a plan in this format that has any error, one line per
finding, before a gate can open on it. The same lint reads an outcome at `kb stage review`.

The rule numbers are the contract's, C1 to C26 (the research's `contract-and-parity.md`),
and `ENFORCED` says, per rule, whether a mechanism holds it here: `M` a refusal, `M~` a
refusal of the common failure that cannot judge quality, `R` held by the renderer by
construction, `P` prose only (the brief carries it, nothing checks it).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from keel import merging, planformat, planoutcome, planreview, repolayout
from keel.planformat import UNCLOSED
from keel.planinline import PATH_ONLY, plain, ref_span, walk_links, walk_refs

EM_DASH = "\u2014"
SUMMARY_WORDS = 90          # C1: a few lines, not a page
PROSE_WORDS = 180           # C21: an unbroken paragraph past this is a wall
SHELLS = ("sh", "bash", "zsh", "shell", "console", "text", "")
PLAN_ORDER = ("goal", "now", "target", "proposal", "decisions", "risks", "steps", "proof", "out")
OUTCOME_SECTIONS = ("stands", "next", "why", "questions", "evidence")
# A research outcome (`kind: research`, c-719) IS the research: its light contract. A report
# (`kind: report`) is held to the same one: it is findings by nature, and linted as a plan it
# was asked for a Goal, Decisions and Steps it never has.
RESEARCH_SECTIONS = ("findings", "meaning", "next", "evidence")
RESEARCH_KINDS = ("research", "report")


RECORD = "record"
PLAN = "plan"


def follow_card(doc: dict, card: dict | None, name: str, role: str | None = None) -> list[dict]:
    """A card's document is held to the contract of the ROLE it plays for the CARD (c-719 r1.F1,
    r2.F2, r2.F3), whatever kind it says. The record (`context.md`, role `record`) is an
    outcome: any other kind is read as `outcome`, with a C26 finding, except `research` or
    `report` on a card that writes research (`writes_research`) and `review` on a review card.
    The card's plan (its `plan_ref`, or the `--plan` at planning: role `plan`) naming any kind
    but `plan` is read as `plan`, with a C2 finding. Without this a document could
    skip its contract (C26's five, C27's Risk, C33's boards, C2's plan sections) by naming
    another kind. Called by every lint of a card's documents (`plangate.lint_file`, which
    `kb stage` and the approve check go through, the plan and outcome pages, the row's facts)."""
    card = card or {}
    # a card's context.md is its record whatever asks (a review card's plan_ref names it)
    role = RECORD if name == "context.md" else role
    said, who = doc["kind"], card.get("id") or "this card"
    if role == RECORD:
        if said == "outcome" or (said in RESEARCH_KINDS and writes_research(card)) or (
                said == "review" and review_card(card)):
            return []
        doc["kind"] = "outcome"
        why = ("is not a research card (only a research card, or a card with no repo, writes a "
               "research outcome)" if said in RESEARCH_KINDS else
               "is not a review card" if said == "review" else "keeps its record as an outcome")
        return [finding("C26", f"the record says `kind: {said}`, but {who} {why}: it is read as an "
                               "outcome, held to the outcome's sections")]
    if role == PLAN and said != "plan":
        doc["kind"] = "plan"
        return [finding("C2", f"the plan says `kind: {said}`, but it is {who}'s plan: it is read as a "
                              "plan, held to the plan's sections")]
    return []


def review_card(card: dict) -> bool:
    from keel.review import gate     # noqa: PLC0415 - the review gate imports the plan modules
    return gate.is_review_card(card)


def strict_record(result: dict) -> dict:
    """A comment that never closes is an ERROR in a card's record (c-719 r2.F8): the page draws
    it as text, while a code host's markdown hides everything after it, so the two would read
    differently. In any other document it stays a warning."""
    found = [dict(f, level="error") if f["level"] == "warning" and UNCLOSED in f["text"] else f
             for f in result["findings"]]
    return dict(result, findings=found, ok=not any(f["level"] == "error" for f in found))


def writes_research(card: dict) -> bool:
    """A card whose record may be a research outcome: a research card (`merging.is_research`),
    or a card with no repo, which ships no code (a personal errand or research card, which the
    deck already reads as research). A card with a repo that is not research gets the
    outcome's contract."""
    return merging.is_research(card) or not card.get("repo")


def with_findings(result: dict, extra: list[dict]) -> dict:
    """`result` with `extra` findings first, `ok` counted again."""
    if not extra:
        return result
    found = extra + result["findings"]
    return dict(result, findings=found, ok=not any(f["level"] == "error" for f in found))
PR_SECTIONS = ("summary", "proposal", "design", "findings", "files", "pr_body", "questions")
NONE_LEAD = re.compile(r"^\s*(none|no risks?|nothing)\b", re.I)

ENFORCED = {
    "C1": "M", "C2": "M", "C3": "M~", "C4": "M~", "C5": "P", "C6": "P", "C7": "M",
    "C8": "M", "C9": "M~", "C10": "P", "C11": "M", "C12": "M", "C13": "P", "C14": "M~",
    "C15": "P", "C16": "M", "C17": "M", "C18": "M", "C19": "M~", "C20": "M", "C21": "M",
    "C22": "R", "C23": "R", "C24": "M", "C25": "R", "C26": "M", "C27": "M",
    "C28": "M~", "C29": "M", "C30": "M", "C31": "M", "C32": "M", "C33": "M~",
}
# C28 to C31 are a review card's outcome (`kind: review`, lane RC): `keel/planreview.py`;
# C32 a feature card's (one story's pull requests together, lane GRP), the same module.
# C33 is an outcome's boards and reading order (c-602): `keel/planoutcome.py`.
# C27 is the pre-gate pipeline's risk step (HP-2): an outcome that ships a change carries a
# Risk section naming low, medium or high. `ships` says the card does (keel/review/gate.py).
RISK_LEVEL = re.compile(r"\b(low|medium|med|high)\b", re.I)
# C6 would need to know which repos are frontend repos; no card field says so today, so it
# stays prose until one does (said in docs/plan-format.md, "What is not checked").


def finding(rule: str, text: str, block: str | None = None, level: str = "error") -> dict:
    return {"rule": rule, "text": text, "block": block, "level": level}


def lint(doc: dict, *, repo_card: bool = False, resolve=None, answered=(), board_of=None,
         card_id: str | None = None, ships: bool = False, review: dict | None = None,
         legacy: bool = False, since: str | None = None, written: bool = False,
         changed=None) -> dict:
    """Every finding for one parsed document; `ok` when none is an error.

    `resolve(path, start, end)` answers None for a line that exists at HEAD, else the
    reason; without it path refs are not checked. `answered` is the decision ids he has
    already answered on an earlier revision (C16). `board_of(ref)` answers None for a board
    id that resolves, else the reason; without it board ids are not checked. `card_id`
    goes into the push command a C4 finding prints. `ships` is a card that ships a change,
    whose outcome also carries its Risk (C27). `review` is what a review card's caller knows
    beyond the file (the surviving findings, the last round's ledger; `keel/planreview.py`).
    `legacy` reads a review outcome already at its gate: the old findings shape is a
    warning there, not a refusal (lane FC). `since` is when his plan was approved and
    `written` an outcome already at his gate: C33's boards and reading order, a warning
    there (`keel/planoutcome.py`). `changed()` reads the branch an outcome's `change: none`
    or `change: docs` is checked against (`planoutcome.claim_rules`); None trusts the claim."""
    out: list[dict] = []
    if doc["kind"] == "outcome":
        out += outcome_rules(doc, OUTCOME_SECTIONS)
        if ships:
            out += risk_section_rules(doc)
            out += planoutcome.rules(doc, board_of, since, "warn" if written else "error", changed)
    elif doc["kind"] in RESEARCH_KINDS:
        out += outcome_rules(doc, RESEARCH_SECTIONS, RESEARCH_TITLES)
    elif doc["kind"] == "pr":
        out += outcome_rules(doc, PR_SECTIONS)
    elif doc["kind"] == "review":
        out += summary_rules(doc) + planreview.rules(doc, review, legacy)
    else:
        out += plan_rules(doc, repo_card, answered, card_id)
    if board_of is not None:
        out += board_ref_rules(doc, board_of)
    out += block_rules(doc)
    out += writing_rules(doc)
    if resolve is not None:
        out += ref_rules(doc, resolve)
    return {"ok": not any(f["level"] == "error" for f in out), "findings": out,
            "kind": doc["kind"], "counts": doc.get("counts", {})}


# ----- the plan's structure -----

def plan_rules(doc: dict, repo_card: bool, answered, card_id: str | None = None) -> list[dict]:
    out = summary_rules(doc)
    names = [s["name"] for s in doc["sections"] if s["name"]]
    blocks = list(planformat.all_blocks(doc["blocks"]))
    has_compare = any(b["type"] == "compare" for b in blocks)
    needed = [n for n in PLAN_ORDER if not (n in ("now", "target") and has_compare)]
    if not repo_card:
        needed = [n for n in needed if n not in ("steps", "proof")]
    for name in needed:
        if name not in names:
            out.append(finding(RULE_OF[name], f"the plan has no `## {TITLE_OF[name]}` section"))
    present = [n for n in names if n in PLAN_ORDER]
    if present != sorted(present, key=PLAN_ORDER.index):
        out.append(finding("C2", "the sections are out of order; a plan reads "
                           + ", ".join(TITLE_OF[n] for n in PLAN_ORDER)))
    out += decision_rules(doc, blocks, answered)
    out += risk_rules(doc)
    for name, rule in (("steps", "C18"), ("proof", "C18"), ("out", "C19"), ("proposal", "C9")):
        if name in names and not planformat.section_blocks(doc, name):
            out.append(finding(rule, f"`## {TITLE_OF[name]}` is empty"))
    if repo_card and not any(b["type"] == "board" and b.get("ref") for b in blocks):
        out.append(flow_finding(blocks, card_id))
    return out


def flow_finding(blocks: list[dict], card_id: str | None) -> dict:
    """C4, tightened (P2-7): a repo card's flow is a BOARD the house pushes and embeds by
    id, so the board page lists it under the card and one fix shows in both places. A
    mermaid or inline block is fine for a small picture beside it, never instead of it."""
    push = f"`keel board push --card {card_id or '<card>'} --file flow.txt`"
    drawn = any(b["type"] == "diagram" for b in blocks)
    lead = ("the flow is drawn only inline (mermaid or board lines)" if drawn
            else "a repo card's plan shows its flow")
    return finding("C4", f"{lead}: push it as a board with {push}, then embed it by id "
                         "in a ```board block whose one line is the id it printed (b-NN)")


# What a board id's refusal says when he deleted it (`boards.DELETED_MARK`), spelled here too
# because the refusal may have come from another machine's deck as a sentence.
DELETED_MARK = "is in the trash"


def board_ref_rules(doc: dict, board_of) -> list[dict]:
    """An embedded id that does not resolve draws nothing: an error in any document.

    A board HE DELETED is a warning (BD-2): the embed shows a placeholder, and a card at its
    gate is not refused because of something he did."""
    out = []
    for block in planformat.all_blocks(doc["blocks"]):
        if block["type"] == "board" and block.get("ref"):
            why = board_of(block["ref"])
            if why and DELETED_MARK in why:
                out.append(finding("C4", f"`{block['ref']}` was deleted and {why.split(' ', 1)[-1]}; "
                                         "the page shows a placeholder", block["id"], "warn"))
            elif why:
                out.append(finding("C4", f"`{block['ref']}` does not resolve: {why}", block["id"]))
    return out


def summary_rules(doc: dict) -> list[dict]:
    summary = doc.get("summary")
    if not summary:
        return [finding("C1", "the plan opens with no summary: a paragraph under the title "
                              "saying what the user is being asked to decide")]
    words = len(plain(summary).split())
    if words > SUMMARY_WORDS:
        return [finding("C1", f"the summary is {words} words; keep it to {SUMMARY_WORDS} "
                              "and put the detail below it")]
    first = next((b for b in doc["blocks"] if b["type"] != "heading"), None)
    if first is None or first["type"] != "paragraph" or first["text"] != summary:
        return [finding("C1", "the summary is not the first thing on the page", level="warn")]
    return []


def decision_rules(doc: dict, blocks: list[dict], answered) -> list[dict]:
    out = []
    decisions = [b for b in blocks if b["type"] in ("decision", "batch")]
    ids = {b["id"] for b in decisions}
    under = planformat.section_blocks(doc, "decisions")
    if not decisions and not says_none(under) and not settled(under):
        out.append(finding("C11", "the plan puts no decision to the user: add a ```decision block, "
                                  "a `> [!settled]` callout for one the user already answered, "
                                  "or say `None:` and why under `## Decisions`"))
    for block in decisions:
        if block.get("after") and block["after"] not in ids:
            out.append(finding("C14", f"decision {block['id']} waits on {block['after']!r}, "
                                      "which is not a decision on this plan", block["id"]))
        if block["id"] in set(answered):
            out.append(finding("C16", f"decision {block['id']} was answered on the last "
                                      "revision; fold the answer in and take the block out",
                               block["id"]))
    for block in blocks:
        if block["type"] == "questions":
            for item in block["items"]:
                if "rec" not in item:
                    out.append(finding("C12", f"the open question {item['q_text'][:60]!r} "
                                              "carries no recommendation", block["id"]))
    return out


def risk_rules(doc: dict) -> list[dict]:
    blocks = planformat.section_blocks(doc, "risks")
    if not any(s["name"] == "risks" for s in doc["sections"]):
        return []                     # the missing section is already a finding
    if not blocks:
        return [finding("C17", "`## Risks` is empty: list one, or say `None:` and why")]
    if says_none(blocks) and not re.search(r"none\W+\w+", planformat.text_of(blocks[0]), re.I):
        return [finding("C17", "`None` under Risks needs its reason: `None: <why>`")]
    return []


def settled(blocks: list[dict]) -> bool:
    """A decision he answered, folded into the approved plan (FOLD_IN) as a settled callout."""
    return any(b["type"] == "callout" and b.get("tone") == "settled" for b in blocks)


def says_none(blocks: list[dict]) -> bool:
    return bool(blocks) and bool(NONE_LEAD.match(planformat.text_of(blocks[0]) or ""))


# ----- an outcome's structure (C26) -----

def outcome_rules(doc: dict, required: tuple, titles: dict | None = None) -> list[dict]:
    titles = titles or TITLE_OF
    names = [s["name"] for s in doc["sections"]]
    out = [finding("C26", f"the record has no `## {titles[name]}` section")
           for name in required if name not in names]
    for name in required:
        if name in names and not planformat.section_blocks(doc, name):
            out.append(finding("C26", f"`## {titles[name]}` is empty"))
    if "evidence" in required and "evidence" in names and not shows_evidence(doc):
        out.append(finding("C26", "Evidence names no artifact: a screenshot, a test output "
                                  "file, a `path:line`, or a code block"))
    return out


def outcome_risk(doc: dict) -> str | None:
    """The level an outcome's Risk section names first ("med" is medium), or None."""
    for name in ("risk", "risks"):
        for block in planformat.section_blocks(doc, name):
            found = RISK_LEVEL.search(planformat.text_of(block) or "")
            if found:
                word = found.group(1).lower()
                return "medium" if word == "med" else word
    return None


def risk_section_rules(doc: dict) -> list[dict]:
    names = [s["name"] for s in doc["sections"]]
    if "risk" not in names and "risks" not in names:
        return [finding("C27", "the outcome has no `## Risk` section: low, medium or high, "
                               "and one line why")]
    if outcome_risk(doc) is None:
        return [finding("C27", "`## Risk` names no level: start it with low, medium or high")]
    return []


def shows_evidence(doc: dict) -> bool:
    for block in planformat.section_blocks(doc, "evidence"):
        if block["type"] in ("images", "code", "diff", "copy", "stats", "diagram", "board"):
            return True
        if any(ref.get("kind") == "path" for ref in refs_of(block)):
            return True
        if any(True for _ in links_of(block)):
            return True
    return False


# ----- every block -----

def block_rules(doc: dict) -> list[dict]:
    out = []
    for problem in doc.get("problems", []):
        out.append(finding(problem.get("rule") or rule_for(problem["text"]), problem["text"], problem.get("block"),
                           problem.get("level", "error")))
    for block in planformat.all_blocks(doc["blocks"]):
        if block["type"] == "table" and not block.get("caption"):
            out.append(finding("C20", "a table needs the line above it saying what its rows "
                                      "prove", block["id"]))
        if block["type"] in ("code", "diff"):
            out += code_rules(block)
        if block["type"] == "paragraph" and len(plain(block["text"]).split()) > PROSE_WORDS:
            out.append(finding("C21", f"a paragraph of {len(plain(block['text']).split())} "
                                      f"words; break it up (a list, a table, a callout)",
                               block["id"], "warn"))
    return out


def code_rules(block: dict) -> list[dict]:
    out = []
    if not block.get("why"):
        out.append(finding("C8", "a code block says why to look: ```lang path | why", block["id"]))
    if block["lang"] not in SHELLS and block["type"] == "code" and not block.get("path"):
        out.append(finding("C8", "a code block names its file: ```lang path/to/file.py:12-30 | why",
                           block["id"]))
    return out


def rule_for(text: str) -> str:
    low = text.lower()
    if low.startswith(("finding ", "a finding ")):
        return "C29"                 # a finding block's own grammar (keel/planfinding.py)
    if "recommend" in low or "because" in low:
        return "C12"
    if "compare" in low:
        return "C3"
    if "board" in low or "mermaid" in low or "diagram" in low or "node" in low:
        return "C4"
    return "C11"


# ----- the writing rules (C24) -----

def writing_rules(doc: dict) -> list[dict]:
    raw = str(doc)
    if EM_DASH not in raw:
        return []
    where = [b["id"] for b in planformat.all_blocks(doc["blocks"]) if EM_DASH in str(b)]
    return [finding("C24", "no em-dashes: use commas, colons, parentheses, or a new sentence",
                    block) for block in where or [None]]


# ----- refs resolve at HEAD, a plan's at its `at:`, an outcome's at its tip (C7) -----

THIRD_PARTY_DIRS = ("node_modules", "site-packages", "dist-packages")


def third_party(path: str) -> bool:
    """A dependency's code, which no worktree tracks: cited by line, never checked (C7)."""
    return any(part in THIRD_PARTY_DIRS for part in Path(path).parts)


def has_commit(root: Path, sha: str) -> bool:
    try:
        done = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"],
                              capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


SHA = re.compile(r"^[0-9a-f]{11,40}$")


def card_tips(card: dict) -> list[str]:
    """Where an outcome is read (r-23): the card's branch tip, in order `options.branch`,
    the branch or sha `output_ref` names, the builder's fetched copy of it
    (`refs/builder/<branch>`), then `options.landing.sha` (the tip that landed,
    once the branch is deleted). Every checkout of the repo has them through its refs, so
    the answer no longer depends on which checkout the lint runs in."""
    options = card.get("options") or {}
    landing = options.get("landing") if isinstance(options.get("landing"), dict) else {}
    named = merging.named_branch(card)
    # The builder's branch is fetched into a ref of its own (c-619, `merging.fetch_built`):
    # the live checkout has no `refs/heads` for it, so its outcome is read there.
    built = merging.BUILT_REFS + named if named and not named.startswith(("-", "refs/")) else None
    found = [options.get("branch"), named, built, landing.get("sha")]
    out = []
    for ref in found:
        ref = str(ref or "").strip()
        if ref and ref not in out and not ref.startswith("-"):
            out.append(ref)
    return out


def planned_at(doc: dict) -> list[str]:
    """A plan's `at:`, the commit(s) it was planned against, one per repo; [] for any other
    kind (an outcome describes the change as built, read at the card's tip: `card_tips`)."""
    if doc.get("kind") != "plan":
        return []
    return [sha.strip() for sha in str((doc.get("meta") or {}).get("at") or "").split(",") if sha.strip()]


def ref_rules(doc: dict, resolve) -> list[dict]:
    if planned_at(doc) and hasattr(resolve, "pinned"):
        resolve = resolve.pinned(planned_at(doc))
    elif doc.get("kind") == "outcome" and hasattr(resolve, "tipped"):   # a review reads its detached head
        resolve = resolve.tipped()
    where = getattr(resolve, "rev", "HEAD")
    where = where if where == "HEAD" or not SHA.match(where) else where[:10]
    out, seen = [], set()
    for block in planformat.all_blocks(doc["blocks"]):
        for ref in refs_of(block):
            if ref.get("kind") != "path":
                continue
            key = (ref["path"], ref["start"], ref["end"])
            if key in seen or third_party(ref["path"]):
                continue
            seen.add(key)
            why = resolve(*key)
            if why:
                out.append(finding("C7", f"`{ref['v']}` does not resolve at {where}: {why}", block["id"]))
    return out


def refs_of(block: dict):
    for value in block.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and "t" in item:
                    yield from walk_refs([item])
                elif isinstance(item, dict):
                    yield from refs_of(item)
                elif isinstance(item, list):
                    for sub in item:
                        if isinstance(sub, dict):
                            yield from (walk_refs([sub]) if "t" in sub else refs_of(sub))
    if block.get("type") == "code" and PATH_ONLY.match(block.get("path") or ""):
        yield ref_span("path", block["path"])


def links_of(block: dict):
    """Every link span anywhere in a block (a relative link is a file he can open)."""
    for value in block.values():
        items = value if isinstance(value, list) else []
        for item in items:
            if isinstance(item, dict) and "t" in item:
                yield from walk_links([item])
            elif isinstance(item, dict):
                yield from links_of(item)
            elif isinstance(item, list):
                yield from walk_links([s for s in item if isinstance(s, dict) and "t" in s])


class GitResolver:
    """`path:line` against a checkout's HEAD: the file exists there and has that line.
    `pinned(commits)` reads it at the first of those commits the checkout has instead (a
    plan's `at:`), `tipped()` at the first of the card's `tips` it has (an outcome, r-23),
    and each at HEAD when it has none of them; `rev` says which it read."""

    def __init__(self, root: Path, rev: str = "HEAD", tips: list[str] | None = None):
        self.root, self.rev, self.tips, self.lengths = Path(root), rev, list(tips or []), {}

    def pinned(self, commits: list[str]) -> "GitResolver":
        known = next((sha for sha in commits if has_commit(self.root, sha)), None)
        return GitResolver(self.root, known) if known else self

    def tipped(self) -> "GitResolver":
        return self.pinned(self.tips)

    def __call__(self, path: str, start: int, end: int) -> str | None:
        if path not in self.lengths:
            self.lengths[path] = self.count(path)
        length = self.lengths[path]
        if length is None:
            return "no such file"
        if end > length or start < 1:
            return f"it has {length} lines"
        return None

    def count(self, path: str) -> int | None:
        try:
            done = subprocess.run(["git", "-C", str(self.root), "show", f"{self.rev}:{path}"],
                                  capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0:
            return None
        return done.stdout.count(b"\n") + (0 if done.stdout.endswith(b"\n") or not done.stdout else 1)


class AnyResolver:
    """`path:line` against SEVERAL checkouts (SH-12): a cross-repo card's worktrees. A ref
    resolves when any of them has the line; otherwise the first one's reason, said for all."""

    def __init__(self, roots: list[Path], resolvers: list | None = None):
        self.resolvers = resolvers or [GitResolver(root) for root in roots]

    @property
    def rev(self) -> str:
        return next((r.rev for r in self.resolvers if r.rev != "HEAD"), "HEAD")

    def pinned(self, commits: list[str]) -> "AnyResolver":
        return AnyResolver([], [resolver.pinned(commits) for resolver in self.resolvers])

    def tipped(self) -> "AnyResolver":
        return AnyResolver([], [resolver.tipped() for resolver in self.resolvers])

    def __call__(self, path: str, start: int, end: int) -> str | None:
        reasons = []
        for resolver in self.resolvers:
            why = resolver(path, start, end)
            if why is None:
                return None
            reasons.append(why)
        if len(reasons) < 2:
            return reasons[0] if reasons else "no worktree to check it in"
        return f"{reasons[0]} in any of the card's {len(reasons)} worktrees"


def card_roots(card: dict, first: Path | None) -> list[Path]:
    """Every worktree of a card a ref may point into, `first` (the house's own) leading:
    a work card's recorded `options.worktree` and `options.worktrees` (SH-12), a feature
    review card's `options.review_worktrees`, and a
    personal card's `<id>-<repo>` beside an `<id>` worktree (`adapters.worktree_dirs`).
    Each directory once, and only the ones on disk and not empty (`repolayout.holds_tree`)."""
    options = card.get("options") or {}
    found = [first] if first else []
    found += [Path(str(options["worktree"]))] if options.get("worktree") else []
    recorded = options.get("worktrees") or {}
    found += [Path(str(path)) for path in (recorded.values() if isinstance(recorded, dict) else ())]
    # a feature review card's members' checkouts (lane GRP), c-511: its refs span them all
    members = options.get("review_worktrees") or {}
    found += [Path(str(path)) for path in (members.values() if isinstance(members, dict) else ())]
    repos = [key.strip() for key in str(card.get("repo") or "").split(",") if key.strip()]
    for root in list(found):
        if root.name == card.get("id"):
            found += [root.parent / f"{card['id']}-{key}" for key in repos[1:]]
    out, seen = [], set()
    for root in found:
        key = str(root.expanduser().resolve())
        if key not in seen and repolayout.holds_tree(root):
            seen.add(key)
            out.append(root)
    return out


def card_resolver(card: dict, first: Path | None):
    """The C7 resolver for a card: its one worktree, or all of them for a cross-repo card;
    None when it has none on disk. Each carries the card's tips, where an outcome is read."""
    roots, tips = card_roots(card, first), card_tips(card)
    if not roots:
        return None
    resolvers = [GitResolver(root, tips=tips) for root in roots]
    return resolvers[0] if len(resolvers) == 1 else AnyResolver([], resolvers)


RULE_OF = {"goal": "C2", "now": "C2", "target": "C2", "proposal": "C9", "decisions": "C11",
           "risks": "C17", "steps": "C18", "proof": "C18", "out": "C19"}
TITLE_OF = {"goal": "Goal", "now": "Now", "target": "Target", "proposal": "Proposal",
            "decisions": "Decisions", "risks": "Risks", "steps": "Steps", "proof": "Proof",
            "out": "Out of scope", "stands": "Where it stands", "next": "What is next",
            "why": "Why this shape", "questions": "Open questions", "evidence": "Evidence",
            "summary": "Summary", "design": "Design decisions and constraints",
            "findings": "Review findings", "files": "Files touched", "pr_body": "PR body",
            "risk": "Risk", "orientation": "Orientation", "verdict": "Verdict",
            "meaning": "What it means"}
# A research outcome's findings are its own, not a review's (c-719).
RESEARCH_TITLES = dict(TITLE_OF, findings="Findings")


def lint_text(text: str, name: str = "plan.md", **kwargs) -> dict:
    return lint(planformat.parse(text, name), **kwargs)


def lines_of(result: dict) -> list[str]:
    """One line per finding, the shape a refusal prints."""
    return [f"{f['rule']} {f['level']}: {f['text']}" + (f" [{f['block']}]" if f.get("block") else "")
            for f in result["findings"]]
