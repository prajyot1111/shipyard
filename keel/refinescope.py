"""The capture refine's reach, enforced by `kb` (review of lane D, item 1; V11 by mechanism).

A refine turn is one bounded model turn over one capture, and the words it is given are his,
verbatim: "block c-312" said into the microphone must stay words on his card, never a block
on c-312. So the gateway runs every refine with `KEEL_REFINE_CARD=<id>` in the turn's
environment (`harbor_voice/refine.py`), and with it set `kb`:

- lets any READ through;
- lets `set`, `note` and `block` through only on that card, and never a `set` of
  `parent`, `after`, `from` or `rank`;
- lets `create` through only `--from` that card and with no `--parent` or `--after`
  (a split child, which Keel's own code files);
- refuses everything else outright, on any card: `split`, the card tree's `tree`,
  `assign`, `next` and `queue`, `unblock`, `stage` (what assigns and
  starts), `approve`, `claim`, `session`, `relay`, `carried`, `event`, `stop-check`,
  `backlog`, `import-harbor`;
- and runs every write as the `voice` actor.

SINCE ROUND 2 THIS IS THE SECOND BELT, NOT THE FIRST. The refine turn has no tools at all
(`harbor_voice/refine.py`) and answers with one JSON object that Keel applies
(`harbor_voice/refineapply.py`); the variable rides on those `kb` calls. Set and empty is a
scope with nothing in it, and refuses every verb.
"""
from __future__ import annotations

import os

ENV = "KEEL_REFINE_CARD"
ACTOR = "voice"
READS = frozenset({"list", "repos", "show", "needs-you", "help"})
ON_ITS_CARD = frozenset({"set", "note", "block"})
# A set that names another card (round 2): a refine never links its card to another one.
# `rank` too (c-302): the queue's order is his, and a refine never moves a card in it.
LINK_FIELDS = ("parent", "after", "from", "rank")


class OutOfScope(Exception):
    """A verb the refine may not run; the message says why."""


def card() -> str:
    return (os.environ.get(ENV) or "").strip()


def scoped() -> bool:
    """Is a scope set at all. SET AND EMPTY COUNTS (round 2): it is a scope that nothing is
    inside, so it refuses everything, rather than reading as "no refine here"."""
    return ENV in os.environ


def check(args) -> None:
    """Raise OutOfScope when this verb is outside the refine's scope. No scope, no check."""
    if not scoped():
        return
    scoped_card = card()
    if not scoped_card:
        raise OutOfScope(f"{ENV} is set but names no card, so nothing is in scope")
    if args.verb in READS:
        return
    check_card(args, scoped_card)


def check_card(args, scoped: str) -> None:
    if args.actor and args.actor != ACTOR:
        raise OutOfScope(f"a refine writes as {ACTOR}, not {args.actor}")
    if args.verb in ON_ITS_CARD:
        if getattr(args, "id", None) != scoped:
            raise OutOfScope(f"a refine may {args.verb} only its own card {scoped}, "
                             f"not {getattr(args, 'id', None)}")
        linked = [item.split("=", 1)[0] for item in getattr(args, "assignments", None) or []
                  if item.split("=", 1)[0] in LINK_FIELDS]
        if linked:
            raise OutOfScope(f"a refine may not set {', '.join(linked)}: it names another card")
        return
    if args.verb == "create":
        if getattr(args, "from_card", None) != scoped:
            raise OutOfScope(f"a refine may create a card only from {scoped} "
                             f"(--from {scoped})")
        if getattr(args, "parent", None) or getattr(args, "after", None):
            raise OutOfScope("a refine's card is never a slice: no --parent, no --after")
        return
    raise OutOfScope(f"a refine may never run `kb {args.verb}`")


def actor(args) -> str | None:
    """The actor a scoped call writes as: always `voice`."""
    return ACTOR if scoped() else args.actor
