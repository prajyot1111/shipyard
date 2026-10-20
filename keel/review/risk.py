"""The risk step (HP-2): low, medium or high, with a one-line why, computed not guessed.

From two things only: the review's SURVIVING findings (a refuted one does not count) and
what the change touches, read from the prepared diff (`review.diff`, one `# repo:` header
per worktree). The house writes the level into its outcome's Risk section, and
`kb stage review` refuses one lower than this (`keel/review/stagecheck.py`): a house may
raise it, never talk it down.

What the change touches is matched on paths, never on a repo's name, so the rule holds in
any repo: a migration, access control or authentication, and more than one repo at once
(a cross-service change).
"""

from __future__ import annotations

import re

from keel.review import findings

LEVELS = ("low", "medium", "high")
REPO_HEADER = re.compile(r"^# repo: (\S+)", re.M)
DIFF_PATH = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)
MIGRATION = re.compile(r"(^|/)(migrations?|alembic)(/|$)|(^|/)versions/.*\.py$|\.sql$", re.I)
ACCESS = re.compile(r"rbac|auth|permission|login|token|secret|credential|acl", re.I)


def touched(diff_text: str) -> dict:
    """The repos and paths a prepared diff touches."""
    repos = list(dict.fromkeys(REPO_HEADER.findall(diff_text or "")))
    paths = list(dict.fromkeys(match.group(2) for match in DIFF_PATH.finditer(diff_text or "")))
    return {"repos": repos, "paths": paths}


def reasons_of(seen: dict) -> list[str]:
    out = []
    if any(MIGRATION.search(path) for path in seen["paths"]):
        out.append("a migration")
    if any(ACCESS.search(path) for path in seen["paths"]):
        out.append("access control or auth")
    if len(seen["repos"]) > 1:
        out.append(f"cross-service ({', '.join(seen['repos'])})")
    return out


def score(found: list[dict], seen: dict) -> dict:
    """`{"level", "why"}` for the surviving findings and what the change touches."""
    alive = findings.surviving(found)
    counts = {sev: sum(1 for one in alive if one["severity"] == sev) for sev in findings.SEVERITIES}
    touches = reasons_of(seen)
    why = [f"{counts[sev]} surviving {sev}" for sev in findings.SEVERITIES if counts[sev]]
    why += [f"touches {reason}" for reason in touches]
    if counts["critical"] or counts["high"] or len(touches) >= 2:
        level = "high"
    elif touches or counts["medium"]:
        level = "medium"
    else:
        level = "low"
    return {"level": level, "why": "; ".join(why) or "no surviving finding, nothing risky touched"}


def rank(level: str | None) -> int:
    """A level's place, or -1 for a word that is not one ("med" is medium)."""
    word = str(level or "").lower()
    word = "medium" if word == "med" else word
    return LEVELS.index(word) if word in LEVELS else -1
