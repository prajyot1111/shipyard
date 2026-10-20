"""The brief's section on the pre-gate pipeline: the same four steps for every repo house.

Review, verify, preship, risk, in that order, then the outcome gate as before (HP-2). The
shape is Keel's and the same in both spaces; the words for verify and preship are the
space's own, from the file its `[spaces.<name>] pipeline` names (a `## Verify` and a
`## Preship` section), so the work space's test and preview tools are named only in
its pack. Each step is held by a mechanism, and the section says which:

- review: the stamp the harness writes and the Stop hook checks (`keel/review/gate.py`);
- verify: the outcome's Evidence section, which the lint requires (C26);
- preship: `kb stage review` refuses a branch that does not contain the base's head, and in
  a `preship_first` space a review pass taken before the draft, or a head no receipt covers
  (c-604);
- risk: the lint requires a Risk section naming a level (C27), and `kb stage review`
  refuses one lower than Keel computed, or a surviving high finding the outcome does not
  name (`keel/review/stagecheck.py`).

Intent is the card's approved plan and its requirements: nothing inside a house derives it
again.
"""

from __future__ import annotations

import re
from pathlib import Path

from keel import terms
from keel.config import DEFAULT_REMOTE
from keel.review import agents, prep, repo, stamp
from keel.review.gate import REQUIREMENTS_FILE

PART = re.compile(r"^## (Verify|Preship|Publish)\s*$", re.M)

GENERIC = {
    "Verify": "Run the repo's own tests, and reproduce the change the way a person meets it "
              "before you trust a green suite. Put what you ran and what it showed under "
              "Evidence in the outcome.",
    "Preship": "",
    "Publish": "",
}

HEAD = """\
### Before you stage review: the pre-gate pipeline

Four steps, in this order, every time, before `kb stage $KEEL_CARD review`.{why} The intent is
this card's approved plan and `{card_dir}/{requirements}` (the card's own words): hold the
change to them, do not derive another.
"""

# c-597: why a space with `preship_first` runs preship first, said once at the top.
FIRST_WHY = (" Preship comes\nfirst, so the head the reviewer sees is the head that ships, and "
             "the slow checks then run\nside by side on that one head: the same checks as ever, "
             "less waiting.")

AGENTS = """Keel defined two read-only agents for this session, on your model:
   `{reviewer}` and `{verifier}`."""

# The review pass itself, the same in both orders: prep, the reviewer, the verifier, answers.
PASS = """
   - `{tool} prep --dir {card_dir} --base {base}{remote_flag}` from your worktree (add
     `--worktree <path>` once per worktree when the card has more than one). It writes
     `{card_dir}/{diff}` and `{card_dir}/{standards}` (the checklist sections of each
     touched repo's own CLAUDE.md, read now, and the test-quality rule).
   - Call the Agent tool with `subagent_type: "{reviewer}"` and ONLY these paths in the
     prompt: the diff, your plan, the requirements, the standards. No account of what you
     did or why: it judges the change, not how you tell it.
   - When it found anything, call `subagent_type: "{verifier}"` with ONLY
     `{card_dir}/{findings}` and the diff. It tries to refute each finding against the code.
   - The harness records both answers (`{findings}`, `{review}`, the stamp); you never
     write those. Fix each high, critical or medium finding that survived, or answer it:
     `{tool} answer --dir {card_dir} <id> --did fixed|declined --why "..."`. LOW findings
     are left as they are by default: decline each with `--why "low, left as is"` and list
     them in the outcome's Review findings. Fix a low one only when it is a true one-liner in
     a file you are already changing for a medium or higher finding, so it rides in that
     fix's check; never commit a fix to low findings alone, and never run a fix check
     for them. It will never be perfect: time goes to what matters."""

FIX_CHECK = """Your fixes
     are then checked, not reviewed again: commit them, `{tool} prep --dir {card_dir}
     --base {base}{remote_flag} --since` (bare: each worktree's reviewed head comes from the stamp; name
     the same `--worktree`s as the full prep, and its `--worktree-base`s when it had any), and call ONLY `{verifier}` with
     `{card_dir}/review-since.diff`, `{card_dir}/review-answers.json` and
     `{card_dir}/{findings}`. When it confirms them the harness moves the stamp to your
     heads. The stamp holds a head per worktree, and `kb stage review` refuses one that
     lacks a worktree of the card."""

EARNED = """
     A second full review is earned only by a fixed high or critical finding (the delta
     check says so), never by the size of the fixes, and never more than {full_max} per
     trip. One fix check covers all your fixes: batch them, do not check after each one.
     When a fix check says a full review is earned, no further fix check can move the
     stamp: run a FULL prep (no `--since`) and ONLY `{reviewer}`; a second such refusal at
     the same count blocks the card, and that full pass clears the block when it writes the
     stamp. A clean rebase needs neither (the stamp matches the
     same change on a newer base)."""

# c-597: a space whose limit is one full pass per trip.
ONE_PASS = """
     This space allows ONE full review pass per trip: a fixed high or critical finding is
     confirmed by the fix check like any other, never by a second full review. One fix check
     covers all your fixes: batch them, do not check after each one. A clean rebase needs
     no new review (the stamp matches the same change on a newer base)."""

REVIEW_SERIAL = """
1. **Review.** """ + AGENTS + PASS + """
   - ONE full review pass per trip to the user's gate, when the build is DONE (every step, tests
     green), never after each commit. A pass the reviewer opened is closed by the verifier
     before anything else: `answer` and `kb stage review` refuse an open pass. """ + FIX_CHECK + """{rounds}
2. **Verify.** {verify}
3. **Preship.** Rebase onto `{base}`'s current head; a conflict you cannot resolve with
   certainty is `kb block $KEEL_CARD` with the conflict, never a guess. Run the repo's
   linters and fix what they fix. `kb stage review` refuses a branch that does not contain
   `{base}`'s head.{preship}
4. """

# c-597: preship first, then verify's slow runs in the background while the review runs.
PRESHIP_FIRST = """
1. **Preship.** `git fetch {remote}`, then rebase onto `{base}`'s current head; a conflict you
   cannot resolve with certainty is `kb block $KEEL_CARD` with the conflict, never a guess.
   Run the repo's linters and fix what they fix.{preship}
   Commit all of it now, before anything is reviewed: `kb stage review` refuses a branch
   that does not contain `{base}`'s head.{publish}
   From here the head is FIXED: commit nothing while the review pass is open, because a
   new commit leaves the reviewer judging a head that will not ship.
2. **Verify, in the background.** Start the slow checks as background jobs (Bash with
   `run_in_background`) on that head, then go straight to the review while they run. A turn
   that ends while a background job or a subagent is still running is a wait, not a stop:
   the harness wakes you when it hands back. {verify}
3. **Review, while they run.** """ + AGENTS + PASS + """
   - ONE full review pass per trip to the user's gate. A pass the reviewer opened is closed by the
     verifier before anything else: `answer` and `kb stage review` refuse an open pass.
     Fixes come after the pass closes, all in one batch; before you commit them, run the
     repo's linters again on the fixed head, and the preship step's docs for any endpoint
     a fix touched, so the head that ships is the one preship would have left. """ + FIX_CHECK + """
     Run the fix check and the verify step's run on the fixed head side by side, as that
     step says.{rounds}
   - `kb stage review` refuses a pass taken before the draft {change} was opened, and a
     head no review receipt covers (after any later commit, `keel check $KEEL_CARD`: it names
     the one step, usually nothing or a fix check).
4. """

RISK = """**Risk.** A `## Risk` section in the outcome: low, medium or high, and one line why.
   `{review}` shows the level Keel computed from the surviving findings and what the change
   touches; yours may be higher, never lower. Name every surviving high or critical
   finding by its id in the outcome. `kb stage review` refuses a lower level or a missing id.

Then stage review: the outcome gate as before."""

BRIEF = HEAD.replace("{why}", "") + REVIEW_SERIAL + RISK


def indented(body: str) -> str:
    """A section's text as it sits under a numbered step: its later lines indented."""
    lines = body.strip().splitlines()
    return "\n".join(lines[:1] + [f"   {line}" if line.strip() else "" for line in lines[1:]])


def space_parts(path: Path | None, **fill) -> dict[str, str]:
    """The space's own verify, preship and publish words, filled; the generic ones where it
    has none."""
    parts = dict(GENERIC)
    try:
        text = Path(path).read_text() if path else ""
    except OSError:
        text = ""
    pieces = PART.split(text)
    for name, body in zip(pieces[1::2], pieces[2::2]):
        parts[name] = indented(body)
    return {name: filled(body, fill) for name, body in parts.items()}


def filled(body: str, fill: dict) -> str:
    """The named placeholders replaced and nothing else, so a brace in a space's own
    words (a JSON example, a shell `${VAR}`) is kept as written."""
    for key, value in fill.items():
        body = body.replace("{" + key + "}", str(value))
    return body


def brief_block(card_dir: Path, base: str, tool: Path, pipeline: Path | None = None,
                tests: str | None = None, preship_first: bool = False,
                full_max: int | None = None, t=None, remote: str | None = None) -> str:
    """The pipeline section: review, verify, preship, risk; or, for a space with
    `preship_first` (c-597), preship with the push and the draft, verify in the background,
    the review on that fixed head, risk. `full_max` is the space's full passes per trip,
    `t` the space's terms (c-630), and `remote` its git remote (c-665)."""
    parts = space_parts(pipeline, tests=tests or "the repo's own test command", base=base,
                        card_dir=card_dir)
    full_max = full_max or stamp.FULL_ROUNDS_MAX
    preship = f"\n   {parts['Preship']}" if parts["Preship"] else ""
    publish = f"\n   {parts['Publish']}" if parts["Publish"] and preship_first else ""
    body = terms.say(t, HEAD.replace("{why}", FIRST_WHY if preship_first else "")
                     + (PRESHIP_FIRST if preship_first else REVIEW_SERIAL) + RISK)
    rounds = ONE_PASS if full_max <= 1 else EARNED.replace("{full_max}", str(full_max))
    return body.replace("{rounds}", rounds).format(
        reviewer=agents.REVIEWER, verifier=agents.VERIFIER, base=base, card_dir=card_dir,
        tool=tool, diff=stamp.DIFF_FILE, standards=prep.STANDARDS_FILE,
        findings=stamp.FINDINGS_FILE, review=stamp.REVIEW_FILE, requirements=REQUIREMENTS_FILE,
        verify=parts["Verify"], preship=preship, publish=publish, remote=remote or DEFAULT_REMOTE,
        remote_flag=repo.remote_flag(remote))


# c-772: a stacked card that names a repo the card it is stacked on does not has a base per
# repo. The review section's last paragraph then names each one, before the parent lands
# and after it has (the house's `house.stack_apart` reads the bases; this is the wording).
PER_REPO = ("\n\nThis card has a base per repo. {how} Its bases: {bases}. `{base}` above is the base in "
            "{first} only. For a worktree of another repo, add `--worktree-base <that worktree> <its "
            "base>` to EVERY prep (the full one and each `--since`), and preship it onto that base.")
PER_REPO_STACKED = ("It is stacked on {parent} in {stacked}, where its {change} is taken against {parent}'s "
                    "branch; in {apart}, which {parent} does not work in, it is cut from that repo's own "
                    "base and its {change} aims at that base.")
PER_REPO_LANDED = ("It was stacked on {parent} in {stacked}, and {parent} has merged, so its {change} there "
                   "now aims at the base {parent} merged into; in {apart}, which {parent} never worked in, "
                   "it keeps that repo's own base.")


def per_repo_block(parent: str, stacked: list[str], apart: list[str], bases: dict, base: str,
                   landed: bool = False, t=None) -> str:
    """`PER_REPO` filled: `bases` is `{repo: base or None}` in the card's repo order, `base`
    the one the section above names (the first repo's)."""
    how = (PER_REPO_LANDED if landed else PER_REPO_STACKED).format(
        parent=parent, stacked=", ".join(stacked), apart=", ".join(apart), change="{change}")
    named = ", ".join(f"`{one}` in {key}" if one else f"none Keel could read in {key} (find it before you prep)"
                      for key, one in bases.items())
    return terms.say(t, PER_REPO.replace("{how}", how)).format(bases=named, base=base, first=next(iter(bases)))


# ----- a review card's steps (peer mode, lane RC) -----

POSTED_OPTION = "review_posted"
LEDGER_FILE = "review-ledger.md"
# His optional focus note from the card's Review settings (2026-09-24), and the file the
# reviewer is handed it in.
FOCUS_OPTION = "review_focus"
FOCUS_FILE = "review-focus.md"

PEER = """\
### The review: Keel's review core, on a colleague's change

This card reviews a {change} someone else wrote. You change nothing in it: you read it,
run the core's two agents on it, and write what survived for the user to post. Nothing you do
stamps the branch or posts anything; the user's Approve posts only what they keep.

1. **Prepare.** `{tool} prep --dir {card_dir} --base {base}{since_flag}` from your worktree.
   It writes `{card_dir}/{diff}` (the {change}'s change against `{base}`) and
   `{card_dir}/{standards}` (each touched repo's own checklist sections, read now, and the
   test-quality rule){since_line}.
2. **Review.** Call the Agent tool with `subagent_type: "{reviewer}"` and ONLY these paths:
   the diff, `{card_dir}/{requirements}` (the {change}'s own title and description){focus_path} and
   the standards{ledger_paths}. No account of your own: it judges the change.{focus}
3. **Verify.** When it found anything, `subagent_type: "{verifier}"` with ONLY
   `{card_dir}/{findings}` and the diff. The harness records both answers (`{findings}`,
   `{review}`); you never write those, and nothing is stamped.
4. **Draft.** For each finding that survived (kept, unverified or disputed), the comment the user
   would post: `{tool} draft --dir {card_dir} <id> --comment "..."`. Polite, specific, one
   point, about the line the finding names, in the user's voice; a question where you are not sure;
   no em-dashes. It refuses a refuted finding and one that names no line.
5. **Write the outcome** in the review kind, as your brief's ending says: a ```finding block
   for every surviving finding (`kb stage review` refuses one that is missing).{ledger}"""

LEDGER = """

The user answered this {change} before, at `{head}` (round {round}). What they posted and what
they dropped is in `{path}`. Never raise one of those again unless `review-since.diff` shows
its lines changed: `kb stage review` refuses a finding at the place of one the user answered whose
lines did not change (C31)."""


def ledger_lines(posted: dict) -> list[str]:
    lines = []
    for one in posted.get("ledger") or []:
        said = "posted" if one.get("choice") != "drop" else "dropped"
        where = f"{one.get('path')}:{one.get('line')}" if one.get("line") else str(one.get("path") or "")
        member = f" on {one['member']}" if one.get("member") else ""
        lines.append(f"- {said} {one.get('id')}{member} at `{where}`: {one.get('claim') or ''}".rstrip(": "))
    return lines


CARRIED_OPTION = "review_carried"


def write_ledger(card_dir: Path, posted: dict, carried: list | None = None) -> Path | None:
    """The last round's answers, rendered for the reviewer from the card (`options.
    review_posted`, the one store), and on a feature card what he answered on a member's
    own single review before it was folded in (`options.review_carried`, lane GRP); None
    when there is nothing he answered."""
    carried = [one for one in carried or [] if one.get("ledger")]
    if not posted.get("head") and not carried:
        return None
    parts = []
    if posted.get("head"):
        parts.append(f"# What the user answered at {str(posted['head'])[:12]}\n\n"
                     + ("\n".join(ledger_lines(posted)) or "Nothing: the review posted no finding."))
    for one in carried:
        parts.append(f"# What the user answered on {one.get('member')} alone, at {str(one.get('head'))[:12]}\n\n"
                     + "\n".join(ledger_lines(one)))
    path = Path(card_dir) / LEDGER_FILE
    path.write_text("\n\n".join(parts) + "\n")
    return path


FOCUS = """

   The user's focus for this review, which the reviewer reads in `{path}`. It says where to look
   hardest; it does not narrow what the reviewer judges:

{text}"""


def quoted(text: str) -> str:
    """His focus note as a quote under a numbered step. Named apart from `indented` (c-597:
    sharing the name made the space's verify and preship words render as a quote too)."""
    return "\n".join("   > " + line for line in text.splitlines())


def write_focus(card_dir: Path, options: dict) -> Path | None:
    """His focus note, rendered for the reviewer from the card (`options.review_focus`, the
    one store); None, and no file left from an earlier round, when there is none."""
    path = Path(card_dir) / FOCUS_FILE
    text = str(options.get(FOCUS_OPTION) or "").strip()
    if not text:
        path.unlink(missing_ok=True)
        return None
    path.write_text(f"# The user's focus for this review\n\n{text}\n")
    return path
FEATURE = """\
### The review: Keel's review core, on a {ticket}'s {changes} together

This card reviews the {changes} of {group} together, as one change: {labels}. Someone else wrote
them. You change nothing: you read them, run the core's two agents on all of them at once,
and write what survived for the user to post. Nothing you do stamps a branch or posts anything;
the user's Approve posts only what they keep, each finding on its own {change}.

1. **Prepare.** One command for all of them, from your worktree:
   `{tool} prep --dir {card_dir} --base {base}{members}{since_flag}`
   It writes `{card_dir}/{diff}` (every {change}'s change against its base, one
   `# repo: <repo> member <label>` header each) and `{card_dir}/{standards}` (each touched
   repo's own checklist sections, the test-quality rule{contract_line}){since_line}.
   A member the adapter calls a TWIN (the same change as another member of its repo, raised
   into another base: your brief's prep line passes it as `--twin`) is not in the diff: it
   gets no finding and no verdict, and the orientation names it with the member it follows;
   the user's Approve gives it one comment pointing at that member's review, and the same verdict.
2. **Review.** Call the Agent tool with `subagent_type: "{reviewer}"` and ONLY these paths:
   the diff, `{card_dir}/{requirements}` (the {changes}' own words) and the
   standards{ledger_paths}. It was defined for this card: each finding names its member (the label of
   the {change} its line is in){contract_agent}.
3. **Verify.** When it found anything, `subagent_type: "{verifier}"` with ONLY
   `{card_dir}/{findings}` and the diff. The harness records both answers (`{findings}`,
   `{review}`); you never write those, and nothing is stamped.
4. **Draft.** For each finding that survived, the comment the user would post on ITS {change}:
   `{tool} draft --dir {card_dir} <id> --comment "..."`. Polite, specific, one point, in the user's
   voice; a contract finding names the other side's `path:line` in its words. No em-dashes.
5. **Write the outcome** in the review kind for a feature, as your brief's ending says: ONE
   orientation for the whole feature (the board draws the path across both repos), every
   surviving finding a row that names its member before its `path:line` (the lint refuses a
   row that names none), and ONE verdict per {change} reviewed (`decision
   verdict-<repo>-<number>` for each, none for a twin: `kb stage review` refuses a member
   with none or two).{ledger}"""

CONTRACT_LINE = ", and the Cross-repo contract check: the change spans more than one repo"
CONTRACT_AGENT = ("; with more than one repo it also runs the Cross-repo contract check "
                  "(paths and methods, field names and casing, error codes, one side changed "
                  "without the other), whose findings have axis `contract`")


def member_flags(options: dict) -> str:
    trees = options.get("review_worktrees") or {}
    return "".join(f" --member {m['label']} {trees.get(m['label']) or '<its worktree>'} "
                   f"{m.get('base') or options.get('base') or '<its base>'}"
                   for m in options.get("review_members") or [])


def feature_block(card_dir: Path, base: str, tool: Path, options: dict, t=None) -> str:
    """A feature card's steps (lane GRP, GR-2): one prep over every member, the contract
    check when the members span more than one repo, a member named on every finding and
    one verdict per change. `t` is the card's space's terms (c-630)."""
    members = options.get("review_members") or []
    posted = options.get(POSTED_OPTION) or {}
    ledger = write_ledger(card_dir, posted, options.get(CARRIED_OPTION))
    since = str(posted.get("head") or "")
    cross = len({m.get("repo") for m in members}) > 1
    return terms.say(t, FEATURE).format(
        group=options.get("review_group") or terms.say(t, "one {ticket}"), labels=", ".join(m["label"] for m in members),
        tool=tool, card_dir=card_dir, base=base, members=member_flags(options), diff=stamp.DIFF_FILE,
        standards=prep.STANDARDS_FILE, requirements=REQUIREMENTS_FILE, findings=stamp.FINDINGS_FILE,
        review=stamp.REVIEW_FILE, reviewer=agents.REVIEWER, verifier=agents.VERIFIER,
        contract_line=CONTRACT_LINE if cross else "", contract_agent=CONTRACT_AGENT if cross else "",
        since_flag="", since_line="",
        ledger_paths=f", and `{ledger}` (what the user answered before, never to be raised again on lines that "
                     f"did not change)" if ledger else "",
        ledger=terms.say(t, LEDGER).format(head=since[:12] or "an earlier head", round=posted.get("round") or 1,
                                           path=ledger)
        if ledger else "")


def peer_block(card_dir: Path, base: str, tool: Path, options: dict, t=None) -> str:
    """A review card's steps: the core's agents in peer mode, then the drafts. `t` is the
    card's space's terms (c-630)."""
    if options.get("review_members"):
        return feature_block(card_dir, base, tool, options, t)
    posted = options.get(POSTED_OPTION) or {}
    ledger = write_ledger(card_dir, posted)
    focus = write_focus(card_dir, options)
    since = str(posted.get("head") or "")
    return terms.say(t, PEER).format(
        tool=tool, card_dir=card_dir, base=base, diff=stamp.DIFF_FILE, standards=prep.STANDARDS_FILE,
        requirements=REQUIREMENTS_FILE, findings=stamp.FINDINGS_FILE, review=stamp.REVIEW_FILE,
        reviewer=agents.REVIEWER, verifier=agents.VERIFIER,
        focus_path=f", `{focus}` (the user's focus for this review)" if focus else "",
        focus=FOCUS.format(path=focus, text=quoted(str(options.get(FOCUS_OPTION)).strip())) if focus else "",
        since_flag=f" --since {since}" if ledger else "",
        since_line=f", and `{card_dir}/{prep.SINCE_FILE}` (what changed since the user last posted)" if ledger else "",
        ledger_paths=(f", `{card_dir}/{prep.SINCE_FILE}` and `{ledger}` (what the user answered "
                      f"last round, never to be raised again on lines that did not change)") if ledger else "",
        ledger=terms.say(t, LEDGER).format(head=since[:12], round=posted.get("round") or 1, path=ledger)
        if ledger else "")

