"""The card pane's controls by phase (c-601): one table, pinned here, in the Atlas, and drawn.

`CONTROL_PHASES` in `app/ui.cards.js` says which stages may show each control of the card
pane. This holds it equal to `PINNED` below and to the Atlas's "Controls by phase" table
(`docs/atlas/40-deck.md`), and runs `tests/fixtures/deck-phases.js`, which renders the pane
in each phase the sandbox end-to-end run met and names every check that did not hold.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from keel import deckstate
from tests.helpers import SESSION, background_row

ROOT = Path(__file__).resolve().parent.parent
ALL = ["inbox", "assigned", "planning", "building", "review", "shipping", "done"]
NOT_DONE = ALL[:-1]
HOUSED = ["planning", "building", "review", "shipping"]

PINNED = {
    **{key: ALL for key in ("answer-ask", "unblock", "dismiss", "end-discussion", "edit", "open-bosun",
                            "on-voice", "in-terminal", "story", "open-pr", "design-doc", "open-plan",
                            "open-output", "open-named", "context", "verb", "flow", "review-settings", "backlog-active",
                            "backlog-auto", "archive")},
    "backlog-send": ["review"],
    "approve-plan": ["planning"], "approve-note": ["planning"], "sendback-stay": ["planning"],
    "sendback": ["planning", "review"], "open-result": ["review"], "open-outcome": ["review"], "approve-outcome": ["review"],
    "open-ci": ["building", "review", "shipping", "done"],
    "open-comments": ["shipping", "done"],
    "worker": ["inbox", "assigned"],
    "answer": HOUSED, "resume": HOUSED, "retry": NOT_DONE,
    "regate": ["inbox", "assigned", "planning", "building", "review"], "logs": ALL, "stop-twin": ALL,
    "split": ["inbox", "assigned", "planning", "building", "shipping"],
    **{key: HOUSED for key in ("open-app", "resume-house", "resume-app", "rotate")},
    "talk-voice": ["planning", "building", "review"], "talk": ["shipping"],
    "stop": HOUSED + ["done"],
    "close-idle": ["review", "shipping"],
    "dropin": ALL, "rereview": ["done"], "review-now": ["inbox", "assigned"],
    "ship": ["shipping"], "assign": ["inbox"],
    "assign-tree": NOT_DONE, "next-front": NOT_DONE, "next-filing": NOT_DONE,
    "need-tracker": ALL, "need-codehost": ["shipping"],
    "ship-why": ["shipping"],      # c-653
    "hand-over": ["shipping"], "hand-base": ["shipping"],      # c-655
    "ship-sendback": ["shipping"],      # c-663
    "ship-prepared": ["shipping"],      # r-55, c-723
}

ROW = re.compile(r"^\| [^|]+ \| ((?:`[\w-]+`(?:, )?)+) \| ([^|]+) \| [^|]+ \|$")


def atlas_table() -> dict:
    text = (ROOT / "docs" / "atlas" / "40-deck.md").read_text()
    section = text.split("### Controls by phase", 1)[1].split("\n#", 1)[0]
    table = {}
    for line in section.splitlines():
        match = ROW.match(line.strip())
        if not match:
            continue
        shown = match.group(2).strip()
        phases = (ALL if shown == "every phase" else NOT_DONE if shown == "every phase but done"
                  else [p.strip() for p in shown.split(",")])
        for key in re.findall(r"`([\w-]+)`", match.group(1)):
            table[key] = phases
    return table


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class ControlPhasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "deck-phases.js"), str(ROOT / "app")],
                                capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def test_the_table_is_the_pinned_one(self):
        self.assertEqual(self.out["table"], PINNED)

    def test_the_atlas_lists_every_control_by_phase(self):
        self.assertEqual(atlas_table(), PINNED)

    def test_every_drawn_control_is_a_row_of_the_table(self):
        for case, keys in self.out["drawn"].items():
            for key in keys:
                self.assertIn(key.split("-")[0] if key.startswith(("verb-", "flow-")) else key, PINNED,
                              f"{case} drew {key}")

    def test_the_pane_draws_what_the_phases_allow(self):
        self.assertEqual(self.out["fails"], [])


class RecordedHouseTest(unittest.TestCase):
    """Logs and Stop act on the card's recorded session; a row matched by name alone (the
    double start's orphan) is marked so the pane does not draw them for it."""

    def test_a_row_matched_by_name_alone_is_not_recorded(self):
        card = {"id": "c-1", "session_id": SESSION}
        own = deckstate.house_row(card, [background_row("c-1", SESSION)])
        self.assertTrue(own["recorded"])
        orphan = deckstate.house_row(card, [background_row("c-1", "bbbbbbbb-0000-4000-8000-000000000002")])
        self.assertFalse(orphan["recorded"])
        self.assertIsNone(deckstate.house_row(card, []))

    def test_a_second_live_session_named_for_the_card_is_a_twin(self):
        """`tellhouse.refuse_twins` tells him to stop the stale one; the pane needs its id."""
        card = {"id": "c-1", "session_id": SESSION}
        stale = "bbbbbbbb-0000-4000-8000-000000000002"
        house = deckstate.house_row(card, [background_row("c-1", SESSION), background_row("c-1", stale)])
        self.assertEqual(house["twins"], [stale[:8]])
        self.assertEqual(deckstate.house_row(card, [background_row("c-1", SESSION)])["twins"], [])



class ReviewHouseTest(unittest.TestCase):
    """c-604: at review a listed idle house read `not listed`, Now said none running, and
    Open in app, Logs and Stop were not drawn: review was not a stage that carries a house."""

    def test_a_card_at_review_carries_its_listed_house_and_is_on_now(self):
        card = {"id": "c-1", "stage": "review", "session_id": SESSION, "blocked_reason": None}
        house = deckstate.live_house(card, [background_row("c-1", SESSION)])
        self.assertIsNotNone(house)
        view = dict(card, house=house, derived={"archived": False, "backlog": False, "tracking": False})
        self.assertEqual(deckstate.houses_of([view]), ["c-1"])


class BlockedShippingTileTest(unittest.TestCase):
    """c-605: a blocked shipping card whose house was listed idle had no Now tile, so the
    tile's one control for it, Unblock only, was nowhere on Now."""

    def test_a_blocked_shipping_card_with_an_idle_house_is_on_now(self):
        card = {"id": "c-1", "stage": "shipping", "session_id": SESSION, "blocked_reason": "the push was refused"}
        house = deckstate.live_house(card, [background_row("c-1", SESSION)])
        view = dict(card, house=house, derived={"archived": False, "backlog": False, "tracking": False})
        self.assertEqual(deckstate.houses_of([view]), ["c-1"])
        self.assertEqual(deckstate.houses_of([dict(view, blocked_reason=None)]), [])
        self.assertEqual(deckstate.houses_of([dict(view, house=None)]), [])

    def test_a_blocked_tracking_parent_at_shipping_gets_no_second_tile(self):
        """c-605 review: its slices' tile already carries it; its own made two tiles, one key."""
        card = {"id": "c-1", "stage": "shipping", "session_id": SESSION, "blocked_reason": "x",
                "house": {"status": "idle"}, "derived": {"archived": False, "backlog": False, "tracking": True}}
        self.assertEqual(deckstate.houses_of([card]), [])


if __name__ == "__main__":
    unittest.main()
