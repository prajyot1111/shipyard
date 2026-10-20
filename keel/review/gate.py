"""Which cards run the pipeline, and the Stop hook's hold on its review step (N4, E-9, HP-2).

The pipeline applies to a repo card in a space whose `house_review` is on
(`[spaces.<name>]`), both spaces since 2026-09-24. Never to an errand or an ask card (no
worktree, no diff), a research card (nothing to ship), or a review card
(`options.review_key`, or `kind = review`): a peer review reads a colleague's branch, and
nothing it does may stamp that branch as reviewed.

The Stop hook (`keel/ending.py`) runs `check` for a card at review whose CURRENT session
was started with the agents (`options.review_session`) and whose ending turn staged review itself (`staged_this_turn`; a
turn that answered his Ask at the gate is never sent back, c-600): when the stamp is not for
the current HEAD of every worktree of the card (a full pass's, or one a fix check moved there,
RD-1; c-581), whatever session wrote it, and not for the same change on a newer base (the
same patch id),
the card goes back to `building`. Twice; the third time the card is blocked for the human,
at review, with the reason. A house started before the agents existed is never held to it.
"""

from __future__ import annotations

from pathlib import Path

from keel import repolayout
from keel.config import Config, remote_of
from keel.review import agents, repo, stamp

REQUIREMENTS_FILE = "requirements.md"
ASKED_OPTION = "review_asked"
SESSION_OPTION = "review_session"
NOT_SHIPPED = ("research", "review")


def is_review_card(card: dict) -> bool:
    options = card.get("options") or {}
    return bool(options.get("review_key")) or options.get("kind") == "review"


def ships_a_change(card: dict) -> bool:
    """A repo card whose house builds a change for a gate: not an ask, research or review."""
    options = card.get("options") or {}
    return bool(card.get("repo") and not options.get("drop")
                and options.get("kind") not in NOT_SHIPPED and not is_review_card(card))


def started_with_pipeline(card: dict) -> bool:
    """A card that ships a change and whose CURRENT session was started with the pipeline
    (`options.review_session`): the only kind the stage checks and C27 hold. A house started
    before the pipeline existed is never held to it."""
    options = card.get("options") or {}
    return (ships_a_change(card) and bool(card.get("session_id"))
            and options.get(SESSION_OPTION) == card["session_id"])


def peer_wanted(cfg: Config, card: dict) -> bool:
    """A review card with a repo (lane RC, RC-2): its house runs the core in PEER mode, the
    same agents and schema with the passes recorded and NO stamp and no hold, whatever the
    space's `house_review` says. It reads a colleague's change; nothing marks that reviewed."""
    return bool(card.get("repo")) and is_review_card(card) and cfg.spaces.get(card["space"]) is not None


def wanted(cfg: Config, card: dict) -> bool:
    """A card that ships a change, in a space with `house_review` on."""
    space = cfg.spaces.get(card["space"])
    return bool(space is not None and getattr(space, "house_review", False) and ships_a_change(card))


# The notes that carry HIS words to the house: a round sent back from a page, and his answer
# to a block (`keel/actions.py`). Their text is what the house was resumed with.
HIS_WORDS = ("The user sent the ", "He sent the ", "answered the block:")


def his_words(events) -> list[tuple[str, str]]:
    """(date, text) of every note of his that redirects the card, oldest first."""
    return [(str(e.get("at") or "")[:10], str(e.get("text") or "").strip()) for e in events or []
            if e.get("kind") == "note" and e.get("actor") == "human"
            and str(e.get("text") or "").startswith(HIS_WORDS)]


def write_requirements(card_dir: Path, card: dict, events=None) -> Path:
    """The card's own words, for the reviewer: its title and brief, then everything he has
    said to redirect it since, in order (RQ-1, c-512: his send-back turned a read-only test
    into a code change, and the reviewer kept judging it against "no commits, no PR"). Nothing
    of the house. Rewritten at every launch and resume."""
    path = card_dir / REQUIREMENTS_FILE
    text = f"# {card.get('title') or card['id']}\n\n{(card.get('brief') or '').strip()}\n"
    said = his_words(events)
    if said:
        text += ("\n## What the user has said since (newest last; it overrides the brief where they differ)\n\n"
                 + "\n\n".join(f"### {day}\n\n{words}" for day, words in said) + "\n")
    path.write_text(text)
    return path


def worktree_of(cfg: Config, card: dict, payload: dict | None) -> str | None:
    """Where the house works: the Stop payload's cwd, else the personal worktree path."""
    cwd = (payload or {}).get("cwd")
    if cwd:
        return cwd
    path = repolayout.card_tree(cfg, card)
    return str(path) if path.is_dir() else None


def covers(stamped: dict, now: dict[str, str], remote: str | None = None) -> bool:
    """True when the stamp reviewed every worktree in `now` (`{root: head}`): each one's head
    is the stamped head for that root (a full pass, or a fix check that moved it there), or
    the same change a clean rebase moved onto a newer base (its patch id). A root the stamp
    has no head for is not covered (c-581, r-28 item 5: on c-272 the stamp tracked one repo
    while the other moved). Whatever session asks (RD-1): a resumed or rotated session on
    reviewed code is not a new change. `remote`: the space's git remote, on which the
    stamped base is read for the patch id (c-665); `origin` for a caller with no space."""
    if not now:
        return False
    stamped_heads = stamp.heads_of(stamped, list(now))
    return all(one_covered(stamped_heads.get(root), root, head, remote) for root, head in now.items())


def one_covered(stamped: dict | None, root: str, head: str, remote: str | None = None) -> bool:
    if not stamped:
        return False
    if stamped.get("head") == head:
        return True
    wanted_id = stamped.get("patch_id")
    return bool(wanted_id) and repo.patch_id(root, repo.base_ref(root, stamped.get("base"), remote)) == wanted_id


def built_covers(cfg: Config, card: dict, live_repo: Path, sha: str, target: str) -> bool:
    """For the builder's card (c-619: its branch is in its clone, `builder.clone_for`): True
    when a complete review Bosun ran from its clones covers every commit the card lands.

    Its own stamp at `sha`, or the stamp on the top of its stack (one review per stack, his
    call 2026-10-04): a pass whose reviewed head holds `sha` and whose base (`base_sha`,
    recorded by prep) is already in `target` where the card's change starts. The card then
    lands only commits that pass read. Unrelated branches each need their own pass. The
    ancestry is read in the clone, which has every commit involved; where the change starts
    is read in the live repo, which has the target."""
    from keel import builder, merging     # noqa: PLC0415 - only the builder's card needs them
    clone = builder.clone_for(cfg, card)
    source = builder.real_clone(cfg, clone) if clone is not None and clone.exists() else None
    if source is None:
        return False
    try:
        starts = merging.git(live_repo, "merge-base", merging.target_head(live_repo, target), sha)
    except merging.MergeRefused:
        return False
    base = str(builder.clones(cfg).resolve())
    for path in sorted(cfg.cards_dir.glob(f"*/{stamp.STAMP_FILE}")):
        for root, entry in stamp.heads_of(stamp.read_json(path, {})).items():
            if not (root and str(root).startswith(base) and entry.get("head")):
                continue
            if entry["head"] == sha:
                return True
            try:
                if (entry.get("base_sha") and merging.ancestor(source, sha, entry["head"])
                        and merging.ancestor(source, entry["base_sha"], starts)):
                    return True
            except merging.MergeRefused:
                continue
    return False


def card_heads(card: dict, cwd) -> dict[str, str]:
    """`{root: head}` for every worktree of the card, the house's own first; the ones whose
    head git cannot read are left out."""
    from keel.planlint import card_roots    # noqa: PLC0415 - planlint is heavier than a hook needs up front
    own = repo.root_of(cwd) if cwd else None
    out = {}
    for root in card_roots(card, own):
        key, head = repo.root_key(root), repo.head_of(root)
        if key and head:
            out[key] = head
    return out


def refusal(card_id: str, path: Path, head: str, found: bool, session_id: str | None = None) -> str:
    """Why the card went back. With a review pass open, finish it; after a fix check that
    earned a full review, that refusal's own sentence (c-529): the generic one sent c-522's
    house round fix checks six times."""
    said = "is from an older change or another session" if found else "is not there"
    opened = stamp.open_round(path.parent)
    if opened:
        step = ("its answer was not the finding schema: call it again" if opened.get("unparsed")
                else f"an earlier session started it and only that session can finish it: call "
                     f"{agents.REVIEWER} again for a new pass" if opened.get("session_id") != session_id
                else f"call {agents.VERIFIER} on its findings, not a fix check")
        return (f"Card {card_id} is not ready for review: the stamp {path} {said}, and review "
                f"pass {opened.get('round')} ({agents.REVIEWER}) is open: {step}. Then stage review again.")
    last = stamp.newest_delta(path.parent)
    if last and last.get("earned") and not last.get("ok"):
        return (f"Card {card_id} is not ready for review: the stamp {path} {said}, and the last "
                f"fix check said {last.get('why')} Then stage review again.")
    return (f"Card {card_id} is not ready for review: {agents.REVIEWER} (and {agents.VERIFIER} "
            f"when it found anything) has not reviewed HEAD ({head[:12]}) of every worktree; the "
            f"stamp {path} {said}. If a closed review pass came before your latest commits, those "
            f"are fixes: a bare `prep --since` (each worktree's reviewed head, from the stamp) and "
            f"ONLY {agents.VERIFIER} on the delta (the harness moves the stamp when it confirms "
            f"them). With no review yet this trip, or a worktree the stamp has no head for, run the "
            f"full review step as your brief says, naming every --worktree. Then stage review again.")


def staged_this_turn(events: list[dict]) -> bool:
    """Did the turn now ending move the card to review? The turn starts at the newest
    `resume` (a resume or a tell, c-598); a move to review older than that was an earlier
    turn's, so this one answered something at his gate (his Ask) and staged nothing (c-600:
    the e2e run's outcome Ask sent the card back to building here)."""
    moved = max((e["id"] for e in events if e.get("kind") == "stage"
                 and (e.get("data") or {}).get("to") == "review"), default=None)
    turn = max((e["id"] for e in events if e.get("kind") == "resume"), default=None)
    return moved is not None and (turn is None or moved > turn)


def check(cfg: Config, board, card: dict, payload: dict | None) -> dict | None:
    """The Stop hook's answer for a card at review: None when there is nothing to refuse.
    Only the turn that staged review is held to the stamp (`staged_this_turn`)."""
    if card["stage"] != "review" or card.get("blocked_reason") or not wanted(cfg, card):
        return None
    if not card.get("session_id") or (card.get("options") or {}).get(SESSION_OPTION) != card["session_id"]:
        return None      # this session was not started with the agents: never held to it
    if not staged_this_turn(board.events(card["id"])):
        return None
    from keel import plangate    # noqa: PLC0415 - plangate imports this module
    if plangate.nothing_to_land(cfg, card, cfg.cards_dir):
        return None      # a verified `change: none`: nothing was built to stamp (r-32, r-33)
    cwd = worktree_of(cfg, card, payload)
    head = repo.head_of(cwd)
    if head is None:
        return None
    stamped = stamp.read_stamp(cfg, card["id"])
    asked = int((card.get("options") or {}).get(ASKED_OPTION) or 0)
    if covers(stamped, card_heads(card, cwd), remote_of(cfg, card.get("space"))):
        if asked:
            board.set_fields(card["id"], {"options": {ASKED_OPTION: None}}, "hook")
        return None
    reason = refusal(card["id"], stamp.stamp_path(cfg, card["id"]), head, bool(stamped), card["session_id"])
    asks = cfg.review_asks       # `[keel] review_asks` (c-633), 2 by default
    if asked >= asks:
        board.block(card["id"], f"the review step still has no stamp for HEAD after {asks} "
                                f"asks: {reason}", "hook", mark="review-limit")
        return None
    board.set_fields(card["id"], {"options": {ASKED_OPTION: asked + 1}}, "hook")
    board.stage(card["id"], "building", "hook", note=reason)
    return {"decision": "block", "reason": reason}
