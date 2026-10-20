"""The standards a review holds a change to (HP-1 d): read at review time, never copied.

For each repo the diff touches, the checklist sections of that repo's OWN `CLAUDE.md`, as
the file says them on the branch under review, plus the one rule every repo gets: the test
quality rule. Nothing here names a repo or quotes a checklist, so a repo that changes its
rules changes the review the next time a house prepares one, with no edit to Keel.

A section is a checklist section when its heading names one of `WORDS` ("Coding
Standards", "Code Review Checklist", Keel's own "Non-negotiable" and "Working here"); its
subsections come with it. A `#` inside a fenced code block is not a heading.
"""

from __future__ import annotations

import re
from pathlib import Path

WORDS = ("standard", "checklist", "non-negotiable", "working here", "conventions")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
FILE = "CLAUDE.md"

TEST_QUALITY_TITLE = "Test quality (every repo)"
TEST_QUALITY = f"""\
## {TEST_QUALITY_TITLE}

A green suite is not evidence that a test is worth keeping. For every test the diff adds or
changes, check that it asserts real behaviour, with an expected value from an independent
source (a known-good literal, a worked example, the requirements), and that the suite covers
the risk-bearing paths: stateful, rollback, mutation and error paths, and the code the
review's own high and medium findings live in. A finding for each test that is:

- tautological: it recomputes the expected value the way the code does, so it passes by
  construction;
- implementation-coupled: it mocks internal collaborators, tests private methods, or checks
  through a side channel, so it breaks on a refactor that kept behaviour;
- horizontally sliced: written against imagined behaviour, asserting shape, insensitive to
  real change;
- padding: covering the easy pure seams while a risk path stays untested (name the path).
"""


def is_checklist(title: str) -> bool:
    low = title.lower()
    return any(word in low for word in WORDS)


def sections(text: str) -> str:
    """The checklist sections of one CLAUDE.md, each with its subsections, in file order."""
    kept, level, fenced = [], None, False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
        match = None if fenced or FENCE.match(line) else HEADING.match(line)
        if match:
            depth = len(match.group(1))
            if level is not None and depth <= level:
                level = None
            if level is None and depth >= 2 and is_checklist(match.group(2)):
                level = depth
        if level is not None:
            kept.append(line)
    return "\n".join(kept).strip()


def repo_block(name: str, root: Path) -> str:
    path = Path(root) / FILE
    try:
        picked = sections(path.read_text(errors="replace"))
    except OSError:
        picked = ""
    head = f"# {name}: the checklist sections of its own {FILE}"
    if not picked:
        return f"{head}\n\n{path} has no checklist section; hold it to the core's checks.\n"
    return f"{head}\n\n(read from {path} at review time)\n\n{picked}\n"


CONTRACT_TITLE = "Cross-repo contract (a change across repos)"
CONTRACT = f"""\
## {CONTRACT_TITLE}

This change spans more than one repo (one feature's changes, reviewed together). The
seam between them is what a review of one side alone cannot see. For every call one side
makes into the other: the path, the HTTP method and the path and query parameters; the
request and response field names, types, casing, enums and nullability; the status codes
and error bodies one side returns against what the other handles; access checks on one side
against gating on the other; and one side changed without the other (a renamed field, a new
required parameter, a removed route). Cite both sides of a mismatch, each at its `path:line`.
"""


def load(touched: dict[str, Path], contract: bool = False) -> str:
    """The standards file: one block per touched repo, the cross-repo contract when the
    change spans more than one repo (lane GRP), then the test-quality rule."""
    blocks = [repo_block(name, root) for name, root in touched.items()]
    return "\n".join(blocks + ([CONTRACT] if contract else []) + [TEST_QUALITY])
