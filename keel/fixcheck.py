"""`keel check <card>`: the one command a house runs after it commits (c-600), which scales
the review of its new commits and says the one next step.

Before a shipping card's commits leave the machine (his Ship), they are reviewed like the
build's were, by Keel's own agents, and the receipt is the ONE review stamp the SubagentStop
hook writes (`keel/review/stamp.py`); nothing else is a receipt. This command decides how
much review the commits need and prepares it:

- **Checked**: the stamp already covers HEAD of every worktree (`review.gate.covers`):
  nothing to do.
- **A fix check**: a closed review pass exists, the stamp has a reviewed head for every
  worktree, and the change since those heads is at most `FIX_MAX` changed lines. It runs
  `prep --since` (each worktree's reviewed head from the stamp) and says to call ONLY the
  verifier on that delta; the hook moves the stamp when it confirms the change.
- **A full pass**: anything else (no pass yet, a worktree the stamp never saw, a bigger
  change). It runs a full `prep` over every worktree and says to call the reviewer, then
  the verifier on its findings.

The stamp hook keeps its own rules (a fix check that earns a full review says so), so this
never overrides it: it only picks the cheaper step when the cheaper step can be enough.
"""

from __future__ import annotations

import sys
from pathlib import Path

from keel import config as config_module
from keel import merging, stacking
from keel.review import agents, prep, stamp
from keel.review import gate as review_gate
from keel.review import repo as review_repo

FIX_MAX = 150
CHECKED = "checked: the review stamp already covers HEAD of every worktree of {id}; nothing to run"
FIX = ("FIX CHECK ({lines} changed lines since the reviewed heads): the delta is in {since}. "
       "Call ONLY {verifier} on it now; the harness moves the stamp when it confirms the change.")
FULL = ("FULL PASS ({why}): {diff} is prepared. Call {reviewer}, then {verifier} on its "
        "findings, and answer each surviving finding with `keel-review answer`.")


def plan(card: dict, card_dir: Path, roots: list[Path], stamped: dict, cwd: Path,
         remote: str | None = None) -> tuple[str, str]:
    """('checked' | 'fix' | 'full', why) for the card's worktrees now, from files alone."""
    if not roots:
        return "full", "no worktree of this card is on this machine"
    if stamped and review_gate.covers(stamped, review_gate.card_heads(card, cwd), remote):
        return "checked", ""
    rounds = stamp.read_rounds(card_dir)
    if not stamped or not rounds or not rounds[-1].get("complete"):
        return "full", "no closed review pass to check fixes against"
    keys = [str(root.resolve()) for root in roots]
    if set(stamp.heads_of(stamped, keys)) != set(keys):
        return "full", "a worktree the stamp has no reviewed head for"
    return "fix", ""


def review_base(cfg, card: dict) -> str | None:
    """c-732: on a repo with an integration branch, that branch once it exists
    (`merging.integration_ref`, None before anything has landed on it, as the stage check reads
    it); before then, a card holding a base of its own reviews against the trunk, which is where
    it was cut from, and any other card against the base its review stamp recorded (None)."""
    space, key = card.get("space"), card.get("repo")
    if not cfg.integration_of(space, key):
        return None
    try:
        found = merging.integration_ref(cfg, space, key)
    except merging.MergeRefused:
        found = None
    if found or not merging.own_base(card):
        return found
    repo = cfg.spaces[space].repo_path(str(key).split(",")[0].strip())
    try:
        return merging.trunk_of(repo) if repo is not None else None
    except merging.MergeRefused:
        return None


NO_REPO = ("{id} has a base per repo (it is stacked on {parent} in {stacked} and not in {apart}), and "
           "Keel cannot tell which of its repos the worktree {root} is, so it will not guess its base. "
           "Run the full prep your brief names, with `--worktree-base {root} <its base>`.")
NO_BASE = ("{id} has a base per repo (it is stacked on {parent} in {stacked} and not in {apart}), and Keel "
           "cannot read a base for {repo} ({root}): no base on the card, no integration branch, no "
           "recorded cut, and the repo's own branch unread. Run the full prep your brief names, with "
           "`--worktree-base {root} <its base>`.")


class NoBase(Exception):
    """A worktree of a card with a base per repo whose base cannot be told (c-772)."""


def own_bases(cfg, card: dict, roots: list[Path]) -> dict:
    """c-772: `{worktree: base}` for EVERY worktree of a stacked card that names a repo its
    parent does not: the parent's branch in the repos they share, its own base in the others,
    each by the one rule (`merging.base_in`). Empty for every other card, which has the one
    base. A worktree whose repo cannot be told, or whose repo has no base the rule can read,
    raises `NoBase` with the sentence: it never takes another repo's base by default. Only a
    directory that is in no worktree of the card's repos is such a worktree."""
    stacked, apart = stacking.split_repos(card)
    if not apart:
        return {}
    from keel import plangate      # noqa: PLC0415 - only a card with a base per repo reads it
    fill = {"id": card["id"], "parent": stacking.of(card)["on"], "stacked": ", ".join(stacked) or "none",
            "apart": ", ".join(apart)}
    out = {}
    for root in roots:
        # the house's cwd leads the list and is often a directory INSIDE a worktree: the
        # worktree it is in is the one asked about (its git toplevel, as the stamp keys it)
        key = plangate.repo_key_of(card, review_repo.root_of(root) or root)
        if key is None:
            raise NoBase(NO_REPO.format(root=root, **fill))
        base = merging.base_in(cfg, card, key)
        if not base:
            raise NoBase(NO_BASE.format(root=root, repo=key, **fill))
        out[str(root)] = base
    return out


def run(cfg, card: dict, cwd: Path) -> str:
    """Prepare the step `plan` picks and say it."""
    from keel.planlint import card_roots          # noqa: PLC0415 - planlint is heavy for a hook
    roots = card_roots(card, cwd)
    card_dir = cfg.card_dir(card["id"])
    base = str(stacking.base_of(card) or merging.card_base(cfg, card) or review_base(cfg, card) or "")
    stamped = stamp.read_stamp(cfg, card["id"])
    remote = config_module.remote_of(cfg, card.get("space"))
    step, why = plan(card, card_dir, roots, stamped, cwd, remote)
    if step == "checked":
        return CHECKED.format(id=card["id"])
    bases = own_bases(cfg, card, roots)      # c-772: raises rather than guess one, once there is a prep to run
    if step == "fix":
        prep.prepare(card_dir, base or stamped.get("base") or "HEAD", roots, since=prep.FROM_STAMP,
                     remote=remote, bases=bases)
        lines = stamp.delta_lines(card_dir)
        if lines <= FIX_MAX:
            return FIX.format(lines=lines, since=card_dir / prep.SINCE_FILE, verifier=agents.VERIFIER)
        why = f"{lines} changed lines since the reviewed heads, more than {FIX_MAX}"
    done = prep.prepare(card_dir, base or stamped.get("base") or "HEAD", roots, remote=remote, bases=bases)
    return FULL.format(why=why, diff=done["diff"], reviewer=agents.REVIEWER, verifier=agents.VERIFIER)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: keel check <card-id>", file=sys.stderr)
        return 2
    from keel.board import open_board
    try:
        cfg = config_module.load()
        board = open_board(cfg)
        try:
            card = board.get(argv[0])
        finally:
            board.close()
        print(run(cfg, card, Path.cwd()))
    except Exception as error:  # noqa: BLE001 - one line, never a traceback, for a house
        print(f"keel check: {error}", file=sys.stderr)
        return 1
    return 0
