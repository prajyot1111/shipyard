"""`demo/seed <phase>`: run a phase, then check what Harbor would read, and say it."""

from __future__ import annotations

import json
import sys

from seeding import parallel, phases
from seeding.day import Day, SeedError

from keel.board import Refused  # noqa: E402

USAGE = "usage: demo/seed history | morning | export [<card>] | breaks | evening | all"


def waiting(day: Day) -> list[str]:
    """Needs you across every space he is read (Harbor's answer), by title."""
    return sorted(card["title"] for card in day.board.needs_you())


def expect(label: str, found, wanted) -> None:
    if found != wanted:
        raise SeedError(f"after {label}, Harbor would read {found!r}, not {wanted!r}")


def check_morning(day: Day) -> None:
    expect("morning", waiting(day), sorted([phases.PLAN_TITLE, "Review: Add a date range filter to /reports",
                                            "Review: Show report totals in the table footer"]))


def check_evening(day: Day) -> None:
    expect("evening", waiting(day), [])
    shipping = sorted(c["title"] for c in day.board.list_cards(stage="shipping"))
    wanted = [*parallel.SHIPPING, *([phases.EXPORT_TITLE] if day.card(phases.EXPORT_TITLE) else [])]
    expect("evening's shipping", shipping, sorted(wanted))


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("history", "morning", "export", "breaks", "evening", "all") or \
            (argv[0] != "export" and len(argv) != 1) or len(argv) > 2:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        day = Day()
        day.stamp_recordings()
        said = {}
        if argv[0] == "history":
            said["history"] = phases.history(day)
        if argv[0] in ("morning", "all"):
            over = phases.evening_done(day)
            said["morning"] = phases.morning(day)
            if not over:
                check_morning(day)
        if argv[0] in ("export", "all"):
            card = argv[1] if len(argv) == 2 else phases.export_card(day)
            said["export"] = phases.export(day, card)
        if argv[0] in ("breaks", "all"):
            said["breaks"] = phases.breaks(day)
        if argv[0] in ("evening", "all"):
            said["evening"] = phases.evening(day)
            check_evening(day)
    except (SeedError, Refused) as error:
        print(f"seed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(said, indent=2, default=str))
    return 0
