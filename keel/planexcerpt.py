"""A review finding's code, pulled from the worktree when the page is drawn (lane FC, FC-2).

The house says WHERE a finding is (`at: path:line` on its `finding` block,
`keel/planfinding.py`), never what the code says: this reads the lines around it from the
card's worktree at HEAD, `CONTEXT` lines either side, so the code he reads beside a comment
is the code that comment lands on and cannot drift from it. It is read where the worktree
is, by the plan route (`keel/planroute.py`).

A single review card's worktree is its house's own (`dropin.cwd_of`, then the card's other
worktrees, `planlint.card_roots`); a feature card's finding is read in ITS member's
(`options.review_worktrees[member]`, lane GRP). HEAD is what is read, not the file on disk,
for the reason C7 checks at HEAD: the review is of what was committed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from keel import dropin
from keel.planlint import card_roots

CONTEXT = 4
MAX_LINES = 60                   # a range longer than this is cut: the card shows its start
MAX_WIDTH = 400                  # a minified line is cut, not sent whole
LANGS = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
         ".cjs": "javascript", ".ts": "javascript", ".tsx": "javascript", ".sql": "sql",
         ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".sh": "bash", ".bash": "bash",
         ".zsh": "bash"}
TREES_OPTION = "review_worktrees"


def lang_of(path: str) -> str | None:
    """The highlighter's language for a file, by its suffix; None when it has none."""
    return LANGS.get(Path(path).suffix.lower())


def head_text(root: Path, path: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{path}"],
                              capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None


def excerpt(root: Path, path: str, start: int, end: int, context: int = CONTEXT) -> dict:
    """`{first, start, end, lines, lang, total}`: the lines from `start - context` to
    `end + context` at HEAD, or `{why}` when the file or the line is not there."""
    text = head_text(Path(root), path)
    if text is None:
        return {"why": f"no such file at HEAD: {path}"}
    lines = text.splitlines()
    if start < 1 or end > len(lines):
        return {"why": f"{path} has {len(lines)} lines at HEAD"}
    last = min(len(lines), end + context, start + MAX_LINES)
    first = max(1, start - context)
    return {"first": first, "start": start, "end": min(end, last), "total": len(lines),
            "lines": [line[:MAX_WIDTH] for line in lines[first - 1:last]], "lang": lang_of(path)}


def first_found(roots: list[Path], path: str, start: int, end: int) -> dict:
    """The excerpt from the first worktree that has the line; the first one's reason else."""
    reasons = []
    for root in roots:
        got = excerpt(root, path, start, end)
        if "lines" in got:
            return got
        reasons.append(got["why"])
    return {"why": reasons[0] if reasons else "no worktree on this machine to read it from"}


def for_doc(doc: dict, trees) -> dict:
    """`{finding id: excerpt}` for every finding block of a document; `trees(member)` gives
    the worktrees to read a finding in, its member's alone on a feature card."""
    out = {}
    for block in walk(doc.get("blocks") or []):
        if block.get("type") == "finding" and block.get("path"):
            out[block["id"]] = first_found(trees(block.get("member")), block["path"], block["start"], block["end"])
    return out


def walk(blocks: list[dict]):
    for block in blocks:
        yield block
        yield from walk(block.get("blocks") or [])


def trees_for(card: dict, first: Path | None):
    """The worktrees a card's finding is read in: its member's, else every one of the card's."""
    members = (card.get("options") or {}).get(TREES_OPTION) or {}

    def trees(member: str | None) -> list[Path]:
        if member and member in members:
            return [Path(members[member])]
        if members:
            return [Path(path) for path in members.values()]
        return card_roots(card, first)
    return trees


def attach(doc: dict, found: dict | None) -> None:
    """Each finding block gets its `code` (the excerpt, or `{why}`), for the page to draw."""
    for block in walk(doc.get("blocks") or []):
        if block.get("type") == "finding" and block["id"] in (found or {}):
            block["code"] = found[block["id"]]


def card_excerpts(cfg, card: dict, doc: dict) -> dict:
    """What the page draws for a card whose worktree is on this machine."""
    if not card.get("repo") or not any(b.get("type") == "finding" for b in walk(doc.get("blocks") or [])):
        return {}
    return for_doc(doc, trees_for(card, dropin.cwd_of(cfg, card)))
