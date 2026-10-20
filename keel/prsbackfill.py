"""`bin/keel-prs-backfill [--dry-run]`: the one-time fill of `options.prs` (c-584).

A card with a pull request in more than one repo reads each of them from `options.prs`
(`{repo: {pr, branch}}`, SH-10): the shipping watcher, the round's worktrees and his Ship all
go by it. c-573 recorded its primary repo's pull request only as `options.pr` (the first one
a house opens) and then its second repo's in `options.prs`, so every per-repo reader saw one
pull request where there were two.

This fills the gap from the card's OWN record and nothing else: for each card at review or
shipping whose `options.pr` is set and whose primary repo (the first of `repo`) has no entry
in `options.prs`, it adds `{pr, branch}` from `options.pr` and `options.branch`, with a note.
It asks no code host (the adapter's, on the machine that holds the house), so it never
checks that the pull request is still open; the shipping watcher does, as before.

`--dry-run` prints what it would write and writes nothing. It writes only what is missing,
so a second run changes nothing. He runs it once after the land, or Bosun does on his word.
"""

import argparse
import sys

from keel import adapters, config as config_module, terms
from keel.board import open_board

ACTOR = "drain"
STAGES = ("review", "shipping")
NOTE = ("options.prs backfill (c-584): recorded {repo} {change} #{pr} here, from the "
        "card's own options.pr, so every per-repo reader sees it")


def missing(card: dict) -> dict | None:
    """The `options.prs` this card should have, or None when it has nothing to add."""
    options = card.get("options") or {}
    repos = adapters.repos_of(card)
    pr = options.get("pr")
    if card.get("stage") not in STAGES or not repos or pr in (None, ""):
        return None
    prs = options.get("prs") if isinstance(options.get("prs"), dict) else {}
    if repos[0] in prs:
        return None
    return dict(prs, **{repos[0]: {"pr": pr, "branch": options.get("branch")}})


def run(board, dry_run: bool = False, out=sys.stdout) -> int:
    """Fill every card that lacks its primary pull request; the count it filled (or would)."""
    filled = 0
    for card in board.list_cards():
        prs = missing(card)
        if prs is None:
            continue
        repo = adapters.repos_of(card)[0]
        entry = prs[repo]
        print(f"{card['id']}  {repo} #{entry['pr']} ({entry['branch'] or 'no branch'})"
              + ("  (dry run: not written)" if dry_run else "  recorded"), file=out)
        filled += 1
        if dry_run:
            continue
        board.set_fields(card["id"], {"options": {"prs": prs}}, ACTOR)
        said = terms.say(terms.of_board(board, card.get("space")), NOTE)
        board.note(card["id"], said.format(repo=repo, pr=entry["pr"]), ACTOR)
    print(f"{filled} card{'s' if filled != 1 else ''} "
          + ("would be filled" if dry_run else "filled"), file=out)
    return filled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keel-prs-backfill", description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print what it would write, write nothing")
    args = parser.parse_args(argv)
    cfg = config_module.load()
    board = open_board(cfg)
    try:
        run(board, dry_run=args.dry_run)
    finally:
        board.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
