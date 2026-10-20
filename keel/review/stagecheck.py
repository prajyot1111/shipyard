"""The pipeline's checks at `kb stage review`: preship and risk, held where the house stages.

They run on the house's machine, before the move is written or sent (`keel/plangate.py`),
for a card that ships a change and whose session was started with the pipeline
(`options.review_session` is its session, the same rule the Stop hook uses): a house
started before the pipeline is never held to it. Each refusal names the fix.

- **Preship**: the branch contains the base's current head (`options.base`, else the
  repo's integration branch, else the branch the repo's main checkout has out), fetched first where there is an origin.
- **Review closed**: the newest review pass is closed (an open or unparsed one names its
  step), and the stamp has a head for every worktree of the card and of the last prep
  (c-581: on c-272 an open pass hid behind an older closed one, and the stamp tracked one
  repo of two).
- **Review answered**: every surviving finding of the newest pass was fixed or answered
  (`keel-review answer`).
- **Risk**: every surviving high or critical finding is named by its id in the outcome, and
  the outcome's Risk is not lower than the level Keel computed.

And in a space with `preship_first` (c-604, `preship_first_check`: in the sandbox no house
did preship first, and none ran `keel check`, while the brief said both):

- **Published before review**: the card's draft pull request was recorded (the `set` event
  that wrote `options.pr` or `options.prs`) no later than this trip's newest full review
  pass. A draft needs its branch pushed, so this is the push too.
- **Checked**: the review stamp, the receipt `keel check` leads to, covers HEAD of every
  worktree of the card. Nothing here runs a test.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from keel import planformat, planlint, stacking
from keel.board import Refused
from keel.config import DEFAULT_REMOTE
from keel.planlint import card_roots
from keel.review import agents, findings, gate, prep, repo, risk, stamp


def worktree_of(card: dict) -> Path | None:
    """The card's worktree: `options.worktree` when it is there, else the checkout `kb` runs in."""
    named = (card.get("options") or {}).get("worktree")
    if named and Path(named).is_dir():
        return repo.root_of(named)
    return repo.root_of(Path.cwd())


OPTION = object()      # `own` not handed in: the card's option, as stored


def base_check(card: dict, worktree: Path, integration: str | None = None,
               remote: str | None = None, own=OPTION) -> None:
    """`own` is the card's own base as the caller's config says it applies (c-732,
    `merging.card_base`: none on a repo with an integration branch, so a card there is checked
    against the trunk while that branch does not exist yet); not handed in, the option."""
    if own is OPTION:
        own = (card.get("options") or {}).get("base")
    # c-732 r2.F1: the integration branch is config, so it beats whatever options.base holds
    # c-772: the stacked base asked for is the card's first repo's, whose worktree this reads
    base = stacking.base_of(card) or integration or own or repo.main_branch(worktree)
    if not base:
        return
    repo.fetch_base(worktree, base, remote)
    ref = repo.base_ref(worktree, base, remote)
    if ref is None or repo.contains(worktree, ref) is not False:
        return
    raise Refused(f"{card['id']} is behind its base: {worktree} does not contain {ref}'s "
                  f"current head. Preship first: `git -C {worktree} rebase {ref}` (a conflict "
                  f"you cannot resolve with certainty is `kb block {card['id']}` with it), "
                  f"review again if the change moved, then stage review.")


def newest_pass(card: dict, card_dir: Path) -> dict | None:
    """The newest pass, refused with its step when it is open; None when there is none."""
    rounds = stamp.read_rounds(card_dir)
    if not rounds:
        return None
    try:
        return prep.newest_pass(rounds)
    except prep.PrepError as error:
        raise Refused(f"{card['id']}: {error}, then stage review.") from None


def heads_check(card: dict, card_dir: Path, worktree: Path | None, remote: str | None = None) -> None:
    """The stamp names a head for every worktree the card has and the last prep saw."""
    roots = {repo.root_key(root) for root in card_roots(card, worktree)}
    roots |= {one.get("root") for one in stamp.read_json(Path(card_dir) / stamp.PREP_FILE, {})
              .get("worktrees") or [] if one.get("root")}
    roots.discard(None)
    stamped = stamp.read_json(Path(card_dir) / stamp.STAMP_FILE, {})
    missing = sorted(roots - set(stamp.heads_of(stamped, sorted(roots))))
    if not missing:
        return
    said = "there is no review stamp" if not stamped else "the review stamp has no head for " + ", ".join(missing)
    flags = " ".join(f"--worktree {root}" for root in sorted(roots))
    raise Refused(f"{card['id']}: {said}. Run the full review step: `keel-review prep --dir "
                  f"{card_dir} --base <base>{repo.remote_flag(remote)} {flags}` (no --since{per_repo(card)}), "
                  f"then {agents.REVIEWER}, then "
                  f"{agents.VERIFIER} on its findings, then stage review.")


def per_repo(card: dict) -> str:
    """c-772: what a printed prep adds for a card with a base per repo (one stacked in only
    some of its repos): the command here names one `--base`, and the brief's has the rest."""
    return ("; this card has a base per repo, so add each `--worktree-base <worktree> <base>` the full "
            "prep in your brief names") if stacking.split_repos(card)[1] else ""


def answered_check(card: dict, card_dir: Path, entry: dict) -> None:
    answers = stamp.read_answers(card_dir)
    open_ids = [one["id"] for one in findings.surviving(entry.get("findings") or [])
                if one["id"] not in answers]
    if open_ids:
        raise Refused(f"{card['id']}: the review's surviving findings {', '.join(open_ids)} are "
                      f"neither fixed nor answered. For each: `keel-review answer --dir {card_dir} "
                      f"<id> --did fixed|declined --why \"...\"`, then stage review.")


def risk_check(card: dict, card_dir: Path, entry: dict) -> None:
    try:
        text = (Path(card_dir) / "context.md").read_text(errors="replace")
    except OSError:
        text = ""
    missing = [one["id"] for one in findings.serious(entry.get("findings") or [])
               if one["id"] not in text]
    if missing:
        raise Refused(f"{card['id']}: the outcome does not name the surviving high or critical "
                      f"findings {', '.join(missing)}; name each by its id (in Risk or Open "
                      f"questions), then stage review.")
    computed = (entry.get("risk") or {}).get("level")
    said = planlint.outcome_risk(planformat.parse(text, "context.md"))
    if computed and risk.rank(said) < risk.rank(computed):
        raise Refused(f"{card['id']}: the outcome's Risk is {said or 'missing'}, lower than the "
                      f"{computed} Keel computed ({(entry.get('risk') or {}).get('why')}). "
                      f"Write `## Risk` as {computed} or higher, with the reason, then stage review.")


def prepared(card_dir: Path) -> bool:
    """True when the house has run the review step here: the one case worth reading the
    card for. A house that has not is sent back by
    the Stop hook anyway, and prepares before it stages again."""
    return any((Path(card_dir) / name).exists() for name in (stamp.PREP_FILE, stamp.FINDINGS_FILE))


def check(card: dict, card_dir: Path, integration: str | None = None,
          remote: str | None = None, own=OPTION) -> None:
    """Refuse the move with the fix, or return: nothing to hold. `integration` is the
    branch the card's repo lands on (c-526), which is then its base; `remote` is the
    space's git remote, which that base is read on (c-665)."""
    if not gate.started_with_pipeline(card):
        return
    worktree = worktree_of(card)
    if worktree is not None:
        base_check(card, worktree, integration, remote, own)
    entry = newest_pass(card, card_dir)
    heads_check(card, card_dir, worktree, remote)
    if entry is not None:
        answered_check(card, card_dir, entry)
        risk_check(card, card_dir, entry)


# ----- preship first (c-604) -----

def at_of(text) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.astimezone()


def trip_start(events: list[dict]) -> datetime | None:
    """When this trip to his gate began: the newest move to building that is not the Stop
    hook's own send-back (`stamp.trip_full_rounds`' rule)."""
    starts = [e.get("at") for e in events or [] if e.get("kind") == "stage" and e.get("actor") != "hook"
              and (e.get("data") or {}).get("to") == "building"]
    return at_of(starts[-1]) if starts else None


def newest_full_pass(card_dir: Path, events: list[dict]) -> datetime | None:
    """When this trip's NEWEST closed full review pass was taken, or None when it had none:
    a house that reviewed before its draft recovers by pushing, drafting and reviewing again
    (c-604 review: the earliest pass could never be undone)."""
    since = trip_start(events)
    taken = [at_of(entry.get("at")) for entry in stamp.read_rounds(card_dir)
             if entry.get("complete") and not entry.get("unparsed")]
    taken = [at for at in taken if at and (since is None or at >= since)]
    return max(taken) if taken else None


def draft_recorded(events: list[dict]) -> datetime | None:
    """When the card's pull request was first recorded on it (`options.pr` or `options.prs`)."""
    found = [at_of(e.get("at")) for e in events or [] if e.get("kind") == "set"
             and any(((e.get("data") or {}).get("options") or {}).get(key) for key in ("pr", "prs"))]
    found = [at for at in found if at]
    return min(found) if found else None


def preship_first_check(card: dict, card_dir: Path, remote: str | None = None) -> None:
    """The order preship first promises, held as a mechanism: the draft before the review,
    and the receipt on the head that ships. Each refusal names what to run."""
    if not gate.started_with_pipeline(card):
        return
    card_dir = Path(card_dir)
    events = card.get("events") or []
    reviewed = newest_full_pass(card_dir, events)
    drafted = draft_recorded(events)
    if reviewed is not None and (drafted is None or drafted > reviewed):
        draft = (f"before its draft was opened ({drafted.isoformat(timespec='seconds')})"
                 if drafted else "with no draft opened")
        raise Refused(
            f"{card['id']}: this space runs preship first, and the review pass was taken "
            f"({reviewed.isoformat(timespec='seconds')}) {draft}, so the host's checks did "
            f"not run beside it on the head that ships. "
            f"Push (`git push -u {remote or DEFAULT_REMOTE} HEAD` from every worktree of the card) and open the "
            f"draft (the Publish step of your brief), then review that head: `keel-review prep "
            f"--dir {card_dir} --base <base>{repo.remote_flag(remote)}` (no --since{per_repo(card)}), "
            f"then {agents.REVIEWER}, then "
            f"{agents.VERIFIER}, then stage review.")
    stamped = stamp.read_json(card_dir / stamp.STAMP_FILE, {})
    if not (stamped and gate.covers(stamped, gate.card_heads(card, worktree_of(card)), remote)):
        raise Refused(
            f"{card['id']}: no review receipt covers HEAD of every worktree (a commit since the "
            f"last review or fix check). Run `keel check {card['id']}` from your worktree and do "
            f"the one step it names, then stage review.")
