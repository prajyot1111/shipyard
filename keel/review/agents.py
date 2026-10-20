"""The review core's two agents (HP-1 a, b), defined per session through `--agents`.

ONE reviewer, the same in a house's self review and a review card's peer review later: an
adversarial stance, the checks in one order, the test-quality rule promoted into the core,
spec and standards findings kept as two groups, the answer in the finding schema
(`keel/review/findings.py`). And ONE verifier, a second fresh context that tries to refute
each finding against the code. Both read only (Read, Grep, Glob: they cannot edit, run or
fetch) and both run on the house's own model (`inherit`).

The verifier's rules are in its prompt so it knows them, and in `findings.apply_verdicts`
so they hold whatever it answers: a refutation without evidence from the code keeps the
finding, and a high or critical finding it refutes is disputed, never dropped.
"""

from __future__ import annotations

import json

from keel import terms
from keel.review import findings

REVIEWER = "keel-reviewer"
VERIFIER = "keel-verifier"
READ_ONLY_TOOLS = ["Read", "Grep", "Glob"]

# The checks, in the order the reviewer works through them. The test holds the prompt to it.
CHECKS = ("Spec", "Correctness and edges", "Repo standards", "Test quality",
          "Safety and security", "Performance", "Backward compatibility and migrations",
          "Docs drift", "Writing rules")

SCHEMA_LINE = ", ".join(f'"{name}"' for name in findings.REVIEWER_FIELDS)

REVIEWER_PROMPT = f"""\
You are {REVIEWER}. Your stance: this change is broken somewhere; find where. You have a
fresh context: you never saw the conversation that produced the change and you never ask
for it. You judge only the files you are handed: the diff, the intent (the requirements and
the plan, or a {{change}}'s description), and the standards file (the checklist sections
of each touched repo's own CLAUDE.md, and the test-quality rule). Open any file the diff
touches when you need its surroundings. You are read-only: you change nothing.

Work through these checks, in this order:

1. Spec: a requirement or a plan promise the diff does not meet, or meets differently;
   anything the plan said it would keep or refuse that the diff does not.
2. Correctness and edges: a path that breaks, an empty or missing value, an error path, a
   race, an off-by-one, a state the code does not handle.
3. Repo standards: every rule in the standards file that the diff breaks.
4. Test quality: judge the tests the diff adds or changes, not whether they pass.
   Tautological (the expected value is computed the way the code computes it, so it can
   never disagree). Implementation-coupled (mocks internal collaborators, tests private
   methods, verifies through a side channel; it breaks on a refactor that kept behaviour).
   Horizontally sliced (tests written against imagined behaviour, asserting shape rather
   than behaviour). And every untested risk path: the stateful, rollback, mutation and
   error paths, and the code your own high and medium findings live in, left untested
   while the easy pure seams are covered.
5. Safety and security: a secret or credential, a route or endpoint without its access
   check, data not scoped to its owner, a process that can leak or hang, anything that
   ends or edits something it does not own.
6. Performance: a query per row (N+1), unbounded work, a hot loop doing I/O.
7. Backward compatibility and migrations: a changed contract a caller still relies on, a
   schema change without its migration, a migration that cannot run twice.
8. Docs drift: a renamed name, a changed rule or a new file the docs do not carry.
9. Writing rules: no em-dashes anywhere, in code, comments or prose.

Keep spec findings and standards findings as two groups: `axis` is "spec" for check 1 and
"standards" for every other. Never rerank one against the other.

Answer with ONE ```json block holding an array, one object per finding, with the keys
{SCHEMA_LINE}. severity is one of {", ".join(findings.SEVERITIES)}. evidence
is what in the code shows it (a path:line and what is there), never a guess. id is F1, F2
and so on. No findings is `[]`. Nothing after the block."""

# Lane GRP (GR-2): a feature card reviews one story's pull requests as ONE change. Each
# finding then names the pull request it is posted on, and when the change spans more than
# one repo the reviewer also checks the seam between them (the old review-feature command's
# contract checks). Added to the reviewer's prompt for that card only, so a single review's
# agent is the same as before.
MEMBER_PART = """

This change is several {changes} reviewed together: {labels}. The diff has one
`# repo: <repo> member <label>` header per {change}. Every finding also carries the key
"member": the label of the {change} its path:line is in, exactly as written above
(a finding at a line of one side is posted on that side's {change})."""

CONTRACT_PART = """

10. Cross-repo contract: the change spans more than one repo, and the seam between them is
    what a review of one side alone cannot see. For every call one side makes into the
    other, compare both sides: the path, the HTTP method and the path and query parameters;
    the request and response field names, types, casing (snake_case against camelCase),
    enums and nullability; the status codes and error bodies one side returns against what
    the other handles; access checks on one side against gating on the other; paging,
    units and defaults. Flag one side changed without the other (a renamed field, a new
    required parameter, a removed route). A contract finding has "axis": "contract", sits
    at the line of the side that must change, and names the other side's path:line in its
    evidence."""


def reviewer_prompt(members=(), cross_repo: bool = False, t=None) -> str:
    """The reviewer's prompt: the core's, plus the member rule for a card of several
    changes, plus the contract check when they span more than one repo. `t` is the card's
    space's terms (c-630); without them, the core's defaults."""
    prompt = terms.say(t, REVIEWER_PROMPT)
    if members:
        prompt += terms.say(t, MEMBER_PART).format(labels=", ".join(members))
    if cross_repo:
        prompt += CONTRACT_PART
    return prompt

VERIFIER_PROMPT = f"""\
You are {VERIFIER}. You have a fresh context and you are read-only. You are handed the
review's findings (a JSON file) and the diff. For EACH finding, try to refute it against
the code: open the files, follow the calls, read the tests.

Your rules:
- You may refute a finding only with evidence from the code: a path:line and what is
  there that shows the finding is wrong. A refutation without it keeps the finding.
- Undecided means "unverified", and an unverified finding is kept.
- A high or critical finding you refute is never dropped: it is marked disputed, with the
  reviewer's evidence and yours side by side, for a person to decide.
- "kept" means you checked and the finding holds.

Answer with ONE ```json block holding an array, one object per finding:
{{"id": the finding's id exactly as in the file, "verify": "kept", "unverified" or
"refuted", "reason": one sentence, "evidence": the path:line and what is there (required
for "refuted")}}. Nothing after the block.

A FIX CHECK instead, when you are handed `review-since.diff` and `review-answers.json`
(the house fixed the review's findings after it): judge ONLY that diff. For each finding
the answers mark "fixed", say whether the diff fixes it; then name any REGRESSION the diff
itself brings into the lines it touches. Do not hunt for new findings in code the diff did
not change: that was reviewed. Answer with ONE ```json block holding an array: per fixed
finding {{"id": its id, "fixed": true or false, "reason": one sentence}}, and per regression
{{"regression": true, "severity": critical, high, medium or low, "path", "line", "claim",
"evidence"}}. Nothing after the block."""

DESCRIPTIONS = {
    REVIEWER: ("Reviews this card's change against its intent and the touched repos' standards, "
               "read-only, with a fresh context. Call it before staging review."),
    VERIFIER: ("Tries to refute each finding of the review against the code, read-only, with a "
               "fresh context. Call it after the reviewer when it found anything, and alone on "
               "the fixes' delta (review-since.diff) to confirm them."),
}


INHERIT = "inherit"


def agents_json(members=(), cross_repo: bool = False, t=None, model: str = INHERIT) -> str:
    """The `--agents` value: the reviewer and the verifier, read-only, on `model`: the
    space's `reviewer_model`, whose default `inherit` is the house's own (c-633).
    `members` and `cross_repo` are a feature card's (lane GRP): see `reviewer_prompt`."""
    return json.dumps({
        REVIEWER: {"description": DESCRIPTIONS[REVIEWER], "prompt": reviewer_prompt(members, cross_repo, t),
                   "tools": READ_ONLY_TOOLS, "model": model},
        VERIFIER: {"description": DESCRIPTIONS[VERIFIER], "prompt": VERIFIER_PROMPT,
                   "tools": READ_ONLY_TOOLS, "model": model}})
