"""`bin/keel-review`: the two commands a house runs in the review step.

- `keel-review prep --dir <card dir> --base <branch> [--worktree <path>]... [--worktree-base
  <path> <branch>]... [--member <label> <worktree> <base>]... [--twin <label> <label it
  follows>]...` writes what
  the reviewer is handed: `review.diff` (the branch's change against the base's current
  head, one `# repo:` header per worktree) and `review-standards.md` (the standards loader,
  `keel/review/standards.py`, for the repos the diff touches). It also records the base in
  `review-prep.json`, which is how the stamp knows what a clean rebase looks like. A
  `--twin` (a feature card's member the adapter says is the same change as another,
  `keel/review/twins.py`) is left out of the diff and named in its member's header. A
  `--worktree-base` (c-772) names the base of ONE of the `--worktree`s where it is not
  `--base`: a stacked card's worktree of a repo the card it is stacked on does not work in.
- `keel-review answer --dir <card dir> <finding id> --did fixed|declined --why "<text>"`
  records what the house did about one finding, in `review-answers.json`, and renders
  `review.md` again. The house never edits review.md: it is rendered from the JSON.
- `keel-review draft --dir <card dir> <finding id> --comment "<text>"` is a review card's
  (lane RC): the drafted public comment for one surviving finding, in its `public_comment`
  slot. `prep --since` also writes `review-since.diff`: bare, each worktree's reviewed head
  from the stamp (a fix check); `--since <sha>` on a re-review.
- `keel-review prompt reviewer|verifier` prints an agent's prompt, and `keel-review record
  --dir <dir> --agent reviewer|verifier --answer-file <file>` records an agent's answer the
  way the SubagentStop hook does. Both are for a review OUTSIDE Keel (the standalone skill),
  where there is no `--agents` and no hook: the same prompts, schema and rules.

No config and no board: both take the card directory the brief names, so they run the same
on the box and on the Mac, in any house.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from keel import terms
from keel.review import agents, repo, standards, stamp, twins

DIFF_FILE = stamp.DIFF_FILE
STANDARDS_FILE = "review-standards.md"
SINCE_FILE = "review-since.diff"
DID = ("fixed", "declined")
EM_DASH = "\u2014"
COMMENT_MAX = 4000


class PrepError(Exception):
    """A request the command cannot carry out; said on stderr, exit 1."""


def prepare(card_dir: Path, base: str, worktrees: list, since: str | None = None,
            members: list | None = None, twin_flags: list | None = None,
            remote: str | None = None, bases: dict | None = None) -> dict:
    """Write the diff, the standards and the base; what was touched. Each worktree's root,
    head and patch id are recorded in `review-prep.json`: the pass the reviewer opens takes
    its heads from there, so a commit made after prep is never stamped as reviewed (c-581).
    With `since` (a fix check) also `review-since.diff`: what changed after the reviewed
    head, per worktree (`FROM_STAMP`, a bare `--since`, takes each one's from the stamp).
    `members` (a feature card, lane GRP) is (label, worktree, base) per pull request: every
    member's change goes into the ONE diff, each under its own header naming its label, and
    the standards gain the cross-repo contract check when more than one repo is touched.
    `twin_flags` is (twin, member it follows) per twin: the twin's diff is left out.
    `bases` (c-772) is `{worktree: base}` for a worktree whose base is not `base`."""
    card_dir = Path(card_dir)
    card_dir.mkdir(parents=True, exist_ok=True)
    own = {str(Path(path).resolve()): str(one) for path, one in (bases or {}).items()}
    sides = [(label, path, own_base or base) for label, path, own_base in members or []] \
        or [(None, path, own.get(str(Path(path).resolve()), base)) for path in worktrees]
    sinces = since_per_root(card_dir, [path for _, path, _ in sides], since) if since else {}
    if sinces:
        (card_dir / SINCE_FILE).write_text(since_diff(sinces))
    parts, touched, seen, read = [], {}, [], []
    for label, worktree, side_base in sides:
        root = repo.root_of(worktree)
        if root is None:
            raise PrepError(f"{worktree} is not a git worktree")
        repo.fetch_base(root, side_base, remote)      # the space's remote (`--remote`, c-665)
        ref = repo.base_ref(root, side_base, remote)
        if ref is None:
            raise PrepError(f"no branch {side_base!r} (nor {remote or repo.DEFAULT_REMOTE}/{side_base}) in {root}")
        name = repo.repo_name(root)
        read.append({"label": label, "repo": name, "base": side_base, "root": root, "ref": ref,
                     "diff": repo.diff(root, ref), "change": repo.git(root, "diff", "-U0", f"{ref}...HEAD") or ""})
        seen.append({"path": str(root), "repo": name, "ref": ref, "member": label,
                     "root": str(root.resolve()), "head": repo.head_of(root), "base": side_base,
                     "base_sha": (repo.git(root, "merge-base", ref, "HEAD") or "").strip() or None,
                     "patch_id": repo.patch_id(root, ref)})
    try:
        found = twins.pair(twin_flags or [], [one for one in read if one["label"]])
    except twins.TwinError as error:
        raise PrepError(str(error)) from None
    twins.write(card_dir, found)
    for one in read:
        if one["label"] in found or not one["diff"].strip():
            continue
        touched[one["repo"]] = one["root"]
        named = f" member {one['label']}" if one["label"] else ""
        also = [f"{label} (the same change on {twin['base']}: not reviewed, the user's Approve points it at "
                f"this member's review and gives it the same verdict)"
                for label, twin in found.items() if twin["primary"] == one["label"]]
        named += f", twin {'; '.join(also)}" if also else ""
        parts.append(f"# repo: {one['repo']}{named} ({one['root']}, against {one['ref']})\n{one['diff']}")
    (card_dir / DIFF_FILE).write_text("\n".join(parts) or "# no change against the base\n")
    (card_dir / STANDARDS_FILE).write_text(standards.load(touched, contract=len(touched) > 1))
    recorded = {"base": base, "worktrees": seen, "at": stamp.now()}
    if sinces:
        # the verifier that finishes next checks this delta, when the newest pass is closed
        recorded["since"] = next(iter(sinces.values()))
        recorded["sinces"] = sinces
    (card_dir / stamp.PREP_FILE).write_text(json.dumps(recorded, indent=2) + "\n")
    return {"diff": str(card_dir / DIFF_FILE), "standards": str(card_dir / STANDARDS_FILE),
            "touched": list(touched), "twins": {label: twin["primary"] for label, twin in found.items()}}


FROM_STAMP = "stamp"


def since_per_root(card_dir: Path, worktrees: list, since: str) -> dict[str, str]:
    """Each worktree's since, by root: a given sha where it is a commit, else the head the
    stamp holds for that worktree (c-581: a reviewed sha is in one repo only). A worktree
    with neither has no reviewed head to check fixes against, which is refused."""
    stamped = stamp.read_json(Path(card_dir) / stamp.STAMP_FILE, {})
    out = {}
    for worktree in worktrees:
        root = repo.root_of(worktree)
        if root is None:
            raise PrepError(f"{worktree} is not a git worktree")
        key = str(root.resolve())
        given = since if since != FROM_STAMP and repo.resolves(root, since) else None
        found = given or (stamp.heads_of(stamped, [key]).get(key) or {}).get("head")
        if not found:
            said = "the stamp" if since == FROM_STAMP else f"{since} is not a commit there, and the stamp"
            raise PrepError(f"no reviewed head for {root}: {said} names none for it. Run a full "
                            f"prep (no --since) naming every --worktree, then the reviewer.")
        out[key] = found
    return out


def since_diff(sinces: dict[str, str]) -> str:
    """The change after the reviewed head, per worktree: what a fix check looks at."""
    parts = []
    for root, since in sinces.items():
        change = repo.git(root, "diff", f"{since}..HEAD")
        if change is None:
            raise PrepError(f"{since} is not a commit {root} has; fetch it first")
        if change.strip():
            parts.append(f"# repo: {repo.repo_name(root)} ({root}, since {since[:12]})\n{change}")
    return "\n".join(parts) or "# nothing changed since the reviewed heads\n"


def newest_pass(rounds: list[dict]) -> dict:
    """The newest pass, the one `answer`, `draft` and `kb stage review` read (c-581: on c-272
    `answer` read the newest COMPLETE pass while a newer one was open, and refused its ids).
    An open pass is refused with its step rather than passed over."""
    if not rounds:
        raise PrepError("no review pass is recorded yet: run prep, then the reviewer")
    entry = rounds[-1]
    if entry.get("unparsed"):
        raise PrepError(f"review pass {entry.get('round')} counts for nothing (its answer was not "
                        f"the finding schema): call {agents.REVIEWER} again")
    if not entry.get("complete"):
        raise PrepError(f"review pass {entry.get('round')} is open: call {agents.VERIFIER} on its "
                        f"findings first")
    return entry


def draft(card_dir: Path, finding_id: str, text: str) -> dict:
    """A review card's drafted public comment for one surviving finding of the newest
    pass (lane RC): put in the finding's `public_comment` slot, and review.md rendered
    again. Refused when it could not be posted as it stands: an empty or over-long comment,
    an em-dash, a refuted finding, or a finding that names no line to post it at."""
    card_dir = Path(card_dir)
    words = str(text or "").strip()
    if not words:
        raise PrepError("a comment that says nothing is not a comment; --comment says it")
    if EM_DASH in words:
        raise PrepError("no em-dashes: use commas, colons, parentheses, or a new sentence")
    if len(words) > COMMENT_MAX:
        raise PrepError(f"a comment is at most {COMMENT_MAX} characters")
    rounds = stamp.read_rounds(card_dir)
    found = newest_pass(rounds).get("findings") or []
    one = next((f for f in found if f["id"] == finding_id), None)
    if one is None:
        raise PrepError(f"{finding_id} is not a finding of the newest review pass "
                        f"({', '.join(f['id'] for f in found) or 'none'})")
    if one.get("verify") == "refuted":
        raise PrepError(f"{finding_id} was refuted by the verifier; there is nothing to post")
    if not (one.get("path") and one.get("line")):
        raise PrepError(f"{finding_id} names no line; a comment is posted at a path:line")
    one["public_comment"] = words
    stamp.save_rounds(card_dir, rounds)
    return one


def answer(card_dir: Path, finding_id: str, did: str, why: str) -> dict:
    """Record the house's answer to one finding of the newest pass, and render again."""
    card_dir = Path(card_dir)
    if did not in DID:
        raise PrepError(f"--did is one of {', '.join(DID)}")
    rounds = stamp.read_rounds(card_dir)
    ids = [one["id"] for one in (newest_pass(rounds).get("findings") or [])]
    if finding_id not in ids:
        raise PrepError(f"{finding_id} is not a finding of the newest review pass ({', '.join(ids) or 'none'})")
    if did == "declined" and not why.strip():
        raise PrepError("a declined finding needs --why")
    answers = stamp.read_answers(card_dir)
    answers[finding_id] = {"did": did, "why": " ".join(why.split()), "at": stamp.now()}
    (card_dir / stamp.ANSWERS_FILE).write_text(json.dumps(answers, indent=2) + "\n")
    stamp.render(card_dir, rounds)
    return answers[finding_id]


PROMPTS = {"reviewer": agents.reviewer_prompt(), "verifier": agents.VERIFIER_PROMPT}


def record(card_dir: Path, agent: str, said: str, worktree) -> dict | None:
    """What the hook does when an agent finishes, for a review with no hook: the pass."""
    head = repo.head_of(worktree)
    if head is None:
        raise PrepError(f"{worktree} is not a git worktree")
    payload = {"cwd": str(worktree), "session_id": "standalone", "last_assistant_message": said}
    if agent == "reviewer":
        return stamp.reviewed(Path(card_dir), payload, head)
    entry = stamp.verified(Path(card_dir), payload)
    if entry is None:
        raise PrepError("no open review pass to verify here; record the reviewer's answer first")
    return entry


def parser() -> argparse.ArgumentParser:
    # allow_abbrev off on every parser (c-730 fix check): a shortened flag (`--d`) is never
    # expanded, so what the board fence reads of a fork house's review step is what runs
    top = argparse.ArgumentParser(prog="keel-review", description="the review step's commands",
                                  allow_abbrev=False)
    subs = top.add_subparsers(dest="command", required=True)
    one = subs.add_parser("prep", allow_abbrev=False, help="write review.diff and review-standards.md")
    one.add_argument("--dir", required=True, help="the card directory")
    one.add_argument("--base", required=True, help="the branch the change is taken against")
    one.add_argument("--remote", default=None, help="the git remote the base is read on (default origin)")
    one.add_argument("--worktree", action="append", default=[], help="a worktree of this card")
    one.add_argument("--worktree-base", nargs=2, action="append", default=[], metavar=("WORKTREE", "BASE"),
                     help="the base of one of the worktrees, where it is not --base")
    one.add_argument("--since", nargs="?", const=FROM_STAMP, default=None,
                     help="a fix check: bare, each worktree's reviewed head from the stamp; "
                          "a sha is used where it is a commit")
    one.add_argument("--member", nargs=3, action="append", default=[], metavar=("LABEL", "WORKTREE", "BASE"),
                     help=terms.say(None, "a feature card's {change} (lane GRP): its label, worktree and base"))
    one.add_argument("--twin", nargs=2, action="append", default=[], metavar=("LABEL", "FOLLOWS"),
                     help="a member that is the same change as another member (c-559): not reviewed")
    two = subs.add_parser("answer", allow_abbrev=False, help="record what you did about one finding")
    two.add_argument("--dir", required=True)
    two.add_argument("id")
    two.add_argument("--did", required=True, choices=DID)
    two.add_argument("--why", default="")
    three = subs.add_parser("prompt", allow_abbrev=False, help="print an agent's prompt (a review outside Keel)")
    three.add_argument("agent", choices=sorted(PROMPTS))
    four = subs.add_parser("record", allow_abbrev=False, help="record an agent's answer (a review outside Keel)")
    four.add_argument("--dir", required=True)
    four.add_argument("--agent", required=True, choices=sorted(PROMPTS))
    four.add_argument("--answer-file", required=True)
    four.add_argument("--worktree", default=None)
    five = subs.add_parser("draft", allow_abbrev=False, help="a review card's public comment for one finding")
    five.add_argument("--dir", required=True)
    five.add_argument("id")
    five.add_argument("--comment", required=True)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "prep":
            done = prepare(Path(args.dir), args.base, args.worktree or [Path.cwd()], since=args.since,
                           members=[tuple(one) for one in args.member],
                           twin_flags=[tuple(one) for one in args.twin], remote=args.remote,
                           bases=dict(args.worktree_base))
            print(f"wrote {done['diff']} and {done['standards']} "
                  f"(touched: {', '.join(done['touched']) or 'nothing'})"
                  + (f" and {Path(args.dir) / SINCE_FILE}" if args.since else ""))
            for twin, primary in done["twins"].items():
                print(f"{twin} is the twin of {primary}: review {primary} only, give {twin} no finding "
                      f"and no verdict, and name it in the orientation as {primary}'s twin")
        elif args.command == "draft":
            draft(Path(args.dir), args.id, args.comment)
            print(f"drafted {args.id}'s comment; {Path(args.dir) / stamp.REVIEW_FILE} rendered")
        elif args.command == "prompt":
            print(PROMPTS[args.agent])
        elif args.command == "record":
            said = Path(args.answer_file).read_text(errors="replace")
            entry = record(Path(args.dir), args.agent, said, args.worktree or Path.cwd())
            scored = entry.get("risk") or {}
            print(f"pass {entry['round']}: {len(entry.get('findings') or [])} findings, "
                  f"risk {scored.get('level')} ({scored.get('why')}); "
                  f"{Path(args.dir) / stamp.REVIEW_FILE} rendered")
        else:
            answer(Path(args.dir), args.id, args.did, args.why)
            print(f"recorded {args.id}: {args.did}; {Path(args.dir) / stamp.REVIEW_FILE} rendered")
    except PrepError as error:
        print(f"keel-review: {error}", file=sys.stderr)
        return 1
    return 0
