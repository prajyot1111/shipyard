"""`bin/keel-shipping-sync [--dry-run]`: every open pull request of his reaches shipping on
the card it belongs to (lane SHIP, SH-6; rebuilt by SH-11).

The first sync moved only cards that RECORDED a pull request and were done, so it moved
nothing: most of his work cards (imported, or closed before Keel tracked pull requests)
record none. This one starts from the code host instead. For each space this machine
serves whose adapter can look at pull requests, it hands the space's cards to the
adapter's `ship mine`, which lists HIS open pull requests in every repo and says which
cards each matches (by the card's branch first, then by the story id in its branch,
tracker reference, title or brief). Then:

- **A pull request matching two cards** goes to the one that already records it, else the
  most recently updated, with a note on the other naming the card it went to.
- **A pull request matching no card** is listed and left alone.
- **Each card** records its pull requests as `options.prs` (`{repo: {pr, branch}}`), and
  `options.pr` and `options.branch` for its primary repo when it has none, and the
  worktree the adapter found for a repo in `options.worktrees`. A repo it has a pull
  request in but did not name is added to `repo`, after the primary, so a review round
  gets a worktree there. Then, when EVERY pull request of the card is open and not a
  draft, a card at done or at review goes to `shipping` (`Board.ship_from_sync`: from
  review this is the sync's own move, noted as such, and it publishes nothing because the
  pull requests are already out); a card with a draft stays where it is; a card already
  shipping has only its record brought up to date; a card at any other stage stays.

It never deletes and never moves a card anywhere but to shipping. `--dry-run` prints every
decision and writes nothing. A second run changes nothing: what is recorded is written
only when it differs, a tie goes where it went before, and a note is never written twice.
Merged pull requests are not listed, so a card whose pull requests all merged stays done.
"""

import argparse
import json
import sys

from keel import adapters, config as config_module, shipping, stacking, terms
from keel.board import SHIPPING_OPTION, Refused, open_board
from keel.config import Config

ACTOR = "drain"
MINE = "mine"
# The notes are templates, filled with the space's words where they are said (c-630).
OPEN_NOTE = "shipping sync: every {change} of this card is open and ready, so it ships until they merge"
REVIEW_NOTE = ("shipping sync: every {change} of this card was already published and ready, "
               "so it moves from review to shipping; nothing was published by this move")
TIE_NOTE = "shipping sync: {repo} {change} #{pr} also matched this card; it went to {winner}"


# ----- what the code host holds -----

def card_view(card: dict) -> dict:
    """What the adapter matches a card on, and nothing else."""
    return {"id": card["id"], "title": card.get("title") or "", "brief": card.get("brief") or "",
            "stage": card.get("stage"), "repo": card.get("repo"), "updated_at": card.get("updated_at"),
            "options": card.get("options") or {},
            "derived": {"tracking": bool(card["derived"].get("tracking")),
                        "archived": bool(card["derived"].get("archived"))}}


def listing(cfg: Config, board, name: str) -> tuple[list[dict], list[dict]]:
    """The space's cards, and the adapter's `ship mine` over them."""
    space = cfg.spaces[name]
    cards = board.list_cards(space=name, include_archived=False)
    out = adapters.run(space, shipping.SHIP_VERB, MINE, timeout=shipping.SHIP_SECONDS,
                       stdin=json.dumps([card_view(c) for c in cards]))
    found = json.loads(out or "{}")
    return cards, [pr for pr in (found.get("prs") or []) if isinstance(pr, dict)]


# ----- which card each pull request goes to -----

def records(card: dict, pr: dict) -> bool:
    entry = ((card.get("options") or {}).get("prs") or {}).get(pr["repo"]) or {}
    return entry.get("pr") == pr["pr"]


def winner_of(pr: dict, cards: list[dict]) -> tuple[dict, str]:
    """The card that keeps a pull request two cards match, and why: the one that already
    records it (so a second run never moves it), else the most recently updated."""
    holding = [card for card in cards if records(card, pr)]
    if holding:
        return holding[0], "which already records it"
    return max(cards, key=lambda c: (c.get("updated_at") or "", c["id"])), "the most recently updated"


def assign(prs: list[dict], by_id: dict, t=None) -> tuple[dict, list[str], list[tuple[str, str]]]:
    """Each pull request to one card: `{card id: [pr]}`, the lines for the ones with no
    card or a tie, and the notes for the cards that lost a tie."""
    owned, lines, notes = {}, [], []
    for pr in prs:
        cards = [by_id[i] for i in pr.get("cards") or [] if i in by_id]
        label = f"{pr['repo']} #{pr['pr']} ({pr.get('branch') or 'no branch'})"
        if not cards:
            lines.append(f"{label}  no card matches it: left alone")
            continue
        card, why = winner_of(pr, cards)
        owned.setdefault(card["id"], []).append(pr)
        for other in cards:
            if other["id"] != card["id"]:
                notes.append((other["id"], terms.say(t, TIE_NOTE).format(repo=pr["repo"], pr=pr["pr"],
                                                                         winner=card["id"])))
                lines.append(f"{other['id']}  {label} also matched; it went to {card['id']}, {why}")
    return owned, lines, notes


# ----- one card -----

def one_per_repo(prs: list[dict]) -> tuple[dict, list[dict]]:
    """The card's pull request in each repo (the most recently updated, when he has two
    open in one repo for one card), and the ones set aside."""
    kept, aside = {}, []
    for pr in sorted(prs, key=lambda p: p.get("updated") or "", reverse=True):
        if pr["repo"] in kept:
            aside.append(pr)
        else:
            kept[pr["repo"]] = pr
    return kept, aside


def option_changes(card: dict, kept: dict) -> dict:
    """The options the card should record, only the ones that differ from what it has."""
    options = card.get("options") or {}
    repos = adapters.repos_of(card)
    primary = repos[0] if repos else None
    changed = {}
    prs = dict(options.get("prs") or {})
    prs.update({repo: {"pr": pr["pr"], "branch": pr.get("branch")} for repo, pr in kept.items()})
    if prs != (options.get("prs") or {}):
        changed["prs"] = prs
    if primary in kept and not options.get("pr"):
        changed["pr"] = kept[primary]["pr"]
    if primary in kept and not options.get("branch") and kept[primary].get("branch"):
        changed["branch"] = kept[primary]["branch"]
    trees = dict(options.get("worktrees") or {})
    trees.update({repo: pr["worktree"] for repo, pr in kept.items() if pr.get("worktree")})
    if trees != (options.get("worktrees") or {}) and len(set(repos) | set(kept)) > 1:
        changed["worktrees"] = trees
    if primary in kept and kept[primary].get("worktree") and not options.get("worktree"):
        changed["worktree"] = kept[primary]["worktree"]
    return changed


def recorded_fields(card: dict, kept: dict) -> dict:
    fields = {}
    changed = option_changes(card, kept)
    if changed:
        fields["options"] = changed
    repos = adapters.repos_of(card)
    extra = [repo for repo in kept if repo not in repos]
    if extra and not stacking.choice(card):
        fields["repo"] = ",".join(repos + extra)
    return fields


def held_repos(card: dict, kept: dict) -> list[str]:
    """c-718 r2.F2: on a card with a stacked or independent choice its repos are the owner's
    (they decide what it is stacked on), so the sync records the pull requests found there and
    leaves the repo for the owner to add, asked in a note."""
    repos = adapters.repos_of(card)
    return [repo for repo in kept if repo not in repos] if stacking.choice(card) else []


HELD_REPO = ("the shipping sync found this card's {change} in {repos} too, which the card does not "
             "list. It is {choice} (options.stack), so its repos are yours to change: add {repos} with "
             "`kb set {id} repo={grown}` if it belongs here.")


def verdict(card: dict, kept: dict) -> tuple[str | None, str]:
    """Where the card goes (`shipping` or None) and the words for it."""
    drafts = [f"{pr['repo']} #{pr['pr']}" for pr in kept.values() if pr.get("draft")]
    stage = card["stage"]
    if drafts:
        return None, f"stays at {stage}: {', '.join(drafts)} {'is' if len(drafts) == 1 else 'are'} still a draft"
    if stage == "shipping":
        return None, "already shipping"
    if stage == "review" and (card.get("options") or {}).get(SHIPPING_OPTION):
        return None, "stays at review: a review round is at the user's gate"
    if stage in ("done", "review"):
        return "shipping", f"move {stage} to shipping"
    return None, f"stays at {stage}: its house has not finished"


def settle(board, card: dict, prs: list[dict], dry_run: bool, t=None) -> str:
    """Record one card's pull requests and move it, or say why not; the lines it printed."""
    kept, aside = one_per_repo(prs)
    said = ", ".join(f"{repo} #{pr['pr']}" for repo, pr in kept.items())
    if not card.get("repo"):
        return f"{card['id']}  {said}: left alone, it is an errand (no repo)"
    fields = recorded_fields(card, kept)
    target, words = verdict(card, kept)
    would = "would " if dry_run else ""
    grown = f" (repo becomes {fields['repo']})" if "repo" in fields else ""
    record = f"{would}record them{grown}, " if fields else ""
    lines = [f"{card['id']}  {said}: {record}{would if target else ''}{words}"]
    lines += [f"    {pr['repo']} #{pr['pr']} set aside: the card has {pr['repo']} #{kept[pr['repo']]['pr']}"
              for pr in aside]
    held = held_repos(card, kept)
    if held:
        lines.append(f"    {', '.join(held)} not added to repo: the card is {stacking.choice(card)}, so that is the owner's")
    if not dry_run:
        if fields:
            board.set_fields(card["id"], fields, ACTOR)
        if held:
            said_held = terms.say(t, HELD_REPO).format(
                repos=", ".join(held), choice=stacking.choice(card), id=card["id"],
                grown=",".join(adapters.repos_of(card) + held))
            if not noted(board, card["id"], said_held):
                board.note(card["id"], said_held, ACTOR)
        if target:
            note = REVIEW_NOTE if card["stage"] == "review" else OPEN_NOTE
            board.ship_from_sync(card["id"], ACTOR, note=terms.say(t, note))
    return "\n".join(lines)


def noted(board, card_id: str, text: str) -> bool:
    return any(event.get("kind") == "note" and event.get("text") == text
               for event in board.events(card_id, last=0))


# ----- the run -----

def spaces_of(cfg: Config) -> list[str]:
    return [name for name in cfg.served_spaces()
            if adapters.has_verb(cfg.spaces[name], shipping.SHIP_VERB)]


def run_space(cfg: Config, board, name: str, dry_run: bool) -> int:
    cards, prs = listing(cfg, board, name)
    t = terms.of(cfg, name)
    by_id = {card["id"]: card for card in cards}
    owned, lines, notes = assign(prs, by_id, t)
    for card_id, found in owned.items():
        try:
            print(settle(board, by_id[card_id], found, dry_run, t))
        except Refused as refused:
            print(f"{card_id}  refused: {refused}")
    for line in lines:
        print(line)
    if not dry_run:
        for card_id, text in notes:
            if not noted(board, card_id, text):
                board.note(card_id, text, ACTOR)
    return len(prs)


def run(cfg: Config, board, dry_run: bool = False) -> int:
    total = 0
    for name in spaces_of(cfg):
        try:
            total += run_space(cfg, board, name, dry_run)
        except (adapters.AdapterError, ValueError) as error:
            print(f"{name}: could not list the open {terms.of(cfg, name)['changes']}: "
                  f"{str(error).splitlines()[0]}")
            return 1
    print(f"shipping sync: {total} open change(s) of the user's looked at"
          f"{' (dry run: nothing written)' if dry_run else ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keel-shipping-sync", description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print every decision, write nothing")
    args = parser.parse_args(argv)
    cfg = config_module.load()
    board = open_board(cfg)
    try:
        return run(cfg, board, dry_run=args.dry_run)
    finally:
        board.close()


if __name__ == "__main__":
    sys.exit(main())
