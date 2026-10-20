"""The one finding schema, and the verifier's rules applied to it (HP-1 c).

Every review Keel runs speaks this shape: the house's self review today, a review card's
peer review later. A finding is a JSON object:

- `id`: the reviewer's own (`F1`), made unique per pass here (`r2.F1`), because a house
  answers findings by id and a later pass must not answer an earlier one's.
- `axis`: `spec` (does it do what was asked: the requirements, the plan, a PR's intent) or
  `standards` (does it follow the repo's rules, the core's checks), and on a feature card
  across repos `contract` (the seam between them, lane GRP). Groups, never one list, so a
  spec failure is not buried under three tidy standards nits.
- `severity`: critical, high, medium or low.
- `path`, `line`, `claim`, `evidence`, `suggestion`: where, what is wrong, what in the
  code shows it, and what to change.
- `verify`, `verify_reason`, `verify_evidence`: the verifier's verdict. `kept` (it holds),
  `unverified` (undecided, or nobody asked), `disputed` (the verifier refuted a high or
  critical finding: both sides stay), `refuted` (dropped, only with evidence from the code).
- `public_comment`: the draft a peer review posts (a review card, lane RC, fills it with
  `keel-review draft`), None in a self review.
- `member`: on a feature card (lane GRP), the label of the pull request the finding is
  posted on (`cloud#4150`); None otherwise.

The verifier's rules are code, not a sentence in its prompt: `apply_verdicts` is the one
place a finding can be dropped, and it will not drop one without evidence or a high one.
"""

from __future__ import annotations

import json
import re

AXES = ("spec", "standards", "contract")
SEVERITIES = ("critical", "high", "medium", "low")
VERDICTS = ("kept", "unverified", "disputed", "refuted")
REVIEWER_FIELDS = ("id", "axis", "severity", "path", "line", "claim", "evidence", "suggestion")
VERIFY_FIELDS = ("verify", "verify_reason", "verify_evidence")
PEER_FIELDS = ("public_comment",)
# Lane GRP (GR-2): the pull request of a feature card a finding is posted on, its label.
FEATURE_FIELDS = ("member",)
FIELDS = REVIEWER_FIELDS + VERIFY_FIELDS + PEER_FIELDS + FEATURE_FIELDS
AXIS_TITLES = (("spec", "Spec"), ("contract", "Cross-repo contract"), ("standards", "Standards"))
NEVER_DROPPED = ("critical", "high")
DEFAULT_SEVERITY = "medium"
FENCED_JSON = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)
TEXT_MAX = 2000


def text(value, limit: int = TEXT_MAX) -> str:
    return " ".join(str(value or "").split())[:limit]


def line_of(value) -> int | None:
    try:
        number = int(str(value).split("-")[0])
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalise(raw: dict, round_no: int) -> dict:
    """One finding in the schema, whatever the reviewer wrote: unknown values are mended
    to a safe default rather than trusted, and every finding starts unverified."""
    raw = raw if isinstance(raw, dict) else {"claim": str(raw)}
    fid = text(raw.get("id"), 40) or "F"
    severity = str(raw.get("severity") or "").lower()
    axis = str(raw.get("axis") or "").lower()
    return {
        "id": fid if fid.startswith(f"r{round_no}.") else f"r{round_no}.{fid}",
        "axis": axis if axis in AXES else "standards",
        "severity": severity if severity in SEVERITIES else DEFAULT_SEVERITY,
        "path": text(raw.get("path"), 400) or None,
        "line": line_of(raw.get("line")),
        "claim": text(raw.get("claim")),
        "evidence": text(raw.get("evidence")),
        "suggestion": text(raw.get("suggestion")),
        "verify": "unverified",
        "verify_reason": "not verified yet",
        "verify_evidence": "",
        "public_comment": None,
        "member": text(raw.get("member"), 80) or None,
    }


def normalise_all(raws: list, round_no: int) -> list[dict]:
    """The pass's findings, ids unique within it."""
    out, seen = [], set()
    for index, raw in enumerate(raws, start=1):
        one = normalise(raw, round_no)
        if one["id"] in seen:
            one["id"] = f"{one['id']}-{index}"
        seen.add(one["id"])
        out.append(one)
    return out


# ----- reading an agent's answer -----

LINE_ARRAY = re.compile(r"(?m)^\[")


def parse_answer(said: str):
    """The JSON array an agent answered with, from a ```json block or the bare text; None
    when there is none (the answer was not in the schema)."""
    said = said or ""
    candidates = [match.group(1) for match in FENCED_JSON.finditer(said)]
    candidates.append(said.strip())
    # Prose, then the bare array on a line of its own: how an answer handed back through
    # SubagentHandback reads (c-525). From each line that opens with `[` to the last `]`.
    end = said.rfind("]")
    candidates += [said[match.start():end + 1] for match in LINE_ARRAY.finditer(said) if end > match.start()]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            value = value.get("findings", value.get("verdicts"))
        if isinstance(value, list):
            return value
    return None


# ----- the verifier's rules -----

def apply_verdicts(found: list[dict], verdicts: list) -> list[dict]:
    """The findings after the verifier: the one place a finding can be dropped.

    A refutation needs evidence from the code, else the finding stays, unverified. A high
    or critical finding the verifier refutes is never dropped: it is disputed, with both
    sides kept. A finding the verifier said nothing about is undecided: unverified."""
    by_id = {str(v.get("id")): v for v in verdicts or [] if isinstance(v, dict)}
    return [verdict_on(one, by_id.get(one["id"]) or by_id.get(one["id"].split(".", 1)[-1]))
            for one in found]


def verdict_on(one: dict, verdict: dict | None) -> dict:
    one = dict(one)
    if verdict is None:
        return dict(one, verify="unverified", verify_reason="the verifier did not decide it")
    said = str(verdict.get("verify") or "").lower()
    reason, evidence = text(verdict.get("reason")), text(verdict.get("evidence"))
    one.update(verify_reason=reason, verify_evidence=evidence)
    if said == "kept":
        one["verify"] = "kept"
    elif said == "refuted" and not evidence:
        one.update(verify="unverified",
                   verify_reason=f"refuted without evidence from the code, so kept: {reason}".strip(": "))
    elif said == "refuted" and one["severity"] in NEVER_DROPPED:
        one["verify"] = "disputed"
    elif said == "refuted":
        one["verify"] = "refuted"
    else:
        one["verify"] = "unverified"
    return one


def survives(one: dict) -> bool:
    return one.get("verify") != "refuted"


def surviving(found: list[dict]) -> list[dict]:
    return [one for one in found if survives(one)]


def serious(found: list[dict]) -> list[dict]:
    """The surviving high and critical findings: the ones the outcome must name."""
    return [one for one in surviving(found) if one["severity"] in NEVER_DROPPED]


# ----- the file -----

def to_json(found: list[dict]) -> str:
    return json.dumps([{name: one.get(name) for name in FIELDS} for one in found], indent=2)


def from_json(raw: str) -> list[dict]:
    return [{name: one.get(name) for name in FIELDS} for one in json.loads(raw)]


# ----- review.md, rendered -----

def where(one: dict) -> str:
    member = f"{one['member']} " if one.get("member") else ""
    if not one.get("path"):
        return member.strip()
    return member + (f"`{one['path']}:{one['line']}`" if one.get("line") else f"`{one['path']}`")


def render_finding(one: dict, answer: dict | None) -> list[str]:
    lines = [f"- **{one['id']}** {one['severity']}, {one['verify']} {where(one)}: {one['claim']}"]
    if one.get("evidence"):
        lines.append(f"  - Evidence: {one['evidence']}")
    if one.get("suggestion"):
        lines.append(f"  - Suggestion: {one['suggestion']}")
    if one.get("public_comment"):
        lines.append(f"  - Comment to post: {one['public_comment']}")
    if one["verify"] != "unverified" or one.get("verify_reason"):
        tail = f" ({one['verify_evidence']})" if one.get("verify_evidence") else ""
        lines.append(f"  - Verifier: {one['verify']}, {one.get('verify_reason') or 'no reason'}{tail}")
    if answer:
        lines.append(f"  - House: {answer.get('did')}, {answer.get('why') or ''}".rstrip(", "))
    elif survives(one):
        lines.append("  - House: not answered yet")
    return lines


def delta_line(entry: dict) -> list[str]:
    """The pass's newest fix check, when it had one (c-529: a refusal only the JSON held)."""
    deltas = entry.get("deltas") or []
    if not deltas:
        return []
    last = deltas[-1]
    said = "stamp moved" if last.get("ok") else "refused"
    return [f"Fix check {len(deltas)} ({str(last.get('to') or '')[:12]}, {last.get('lines')} "
            f"lines): **{said}**, {last.get('why')}", ""]


def render_round(entry: dict, answers: dict | None = None) -> str:
    """One pass of review.md: the risk, then Spec and Standards as two groups."""
    answers = answers or {}
    head = str(entry.get("head") or "")[:12]
    lines = [f"## Pass {entry.get('round')}, HEAD {head}", ""]
    if entry.get("unparsed"):
        lines += ["The reviewer's answer was not the finding schema, so this pass counts for "
                  "nothing: call it again. What it said:", "", "> " + text(entry.get("said")), ""]
        return "\n".join(lines)
    scored = entry.get("risk") or {}
    if scored:
        lines += [f"Risk Keel computed: **{scored.get('level')}** ({scored.get('why')})", ""]
    lines += delta_line(entry)
    found = entry.get("findings") or []
    if not found:
        return "\n".join(lines + ["No findings.", ""])
    for axis, title in AXIS_TITLES:
        group = sorted((f for f in found if f["axis"] == axis), key=lambda f: SEVERITIES.index(f["severity"]))
        if axis == "contract" and not group:
            continue
        lines.append(f"### {title}")
        lines.append("")
        for one in group:
            lines += render_finding(one, answers.get(one["id"]))
        if not group:
            lines.append("None.")
        lines.append("")
    return "\n".join(lines)


HEADER = ("# Review\n\nRendered by Keel from `review-findings.json` and `review-answers.json`. "
          "Do not edit it: answer a finding with `keel-review answer`.\n\n")


def render(rounds: list[dict], answers: dict | None = None) -> str:
    """The whole review.md: the newest pass first."""
    return HEADER + "\n".join(render_round(entry, answers) for entry in reversed(rounds))
