"""U1 and U2: every card button says what it does, and the look-alikes stop looking alike.

He could not tell Drop in from Resume house on an exited house (2026-09-24). The planner
found the blocked row's "Resume" and the menu's "Resume house" were one verb under two
labels, and that nothing on the deck said what any action does or does not do.

- U1, one name per verb: the blocked row's Resume is "Resume house", the label the menu
  uses, and a card that shows the gate row's does not draw the menu's as well. Unblock is
  "Unblock only", so it cannot read as a resume. The data-keys stay, because the phone
  picks its primaries by key (`PHONE_PRIMARY`).
- U2, a hover line on every action the deck draws for a card, from ONE table keyed by the
  action's data-key (`app/ui.tips.js`), set as `title` and never as `aria-label` (which
  would replace the visible name for a screen reader). Drop in's line follows the state
  it will act on, in `keel/dropin.py`'s own sentences.

These are greps, as `tests/test_deck_css.py` says of itself: a stdlib suite cannot run the
page. The screenshots in the lane's report are the render.
"""

import re
import unittest
from pathlib import Path

from keel import dropin, serve
from tests.test_deck_css import js_function

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TIPS = APP / "ui.tips.js"


def source(name: str) -> str:
    return (APP / name).read_text(encoding="utf-8")


def tip_keys() -> set[str]:
    """The keys of the TIPS table, read from its own block."""
    text = source("ui.tips.js")
    start = text.index("var TIPS = {")
    depth, i = 0, start + len("var TIPS = ")
    while True:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            break
    block = text[start:i]
    return set(re.findall(r"^\s*'([a-z-]+)':", block, re.M))


def drawn_keys(module: str, *functions: str) -> set[str]:
    """Every literal key an action is drawn under in these functions: `put('k'` and
    `keyed('k'`."""
    keys = set()
    for name in functions:
        body = js_function(module, name)
        keys |= set(re.findall(r"\b(?:put|keyed)\('([a-z-]+)'", body))
    # `put('verb-' + v.verb, ...)`: an adapter verb, whose line is its own `help`; and
    # `put('flow-' + m.id, ...)`, a flow move, whose line is its own `about` (c-640)
    return {key[:-1] if key.endswith("-") else key for key in keys}


class OneNamePerVerbTest(unittest.TestCase):

    def test_the_menu_does_not_draw_a_second_resume_house_beside_the_gate_row_s(self):
        body = js_function("ui.cards.js", "cardItems")
        line = next(l for l in body.splitlines() if "put('resume-house'" in l)
        self.assertIn("K.gateOf(c) !== 'blocked'", line)


class EveryActionHasALineTest(unittest.TestCase):
    def test_every_key_the_card_draws_has_an_entry(self):
        drawn = drawn_keys("ui.cards.js", "gateActions", "cardItems", "phoneSplit",
                           "phoneActions", "backlogActions", "putCi", "putWorker", "putNamed")
        self.assertGreater(len(drawn), 25)
        missing = sorted(drawn - tip_keys())
        self.assertEqual(missing, [], f"drawn with no hover line: {missing}")

    def test_every_entry_is_drawn_somewhere(self):
        """The other direction: a line for an action nothing draws is wording nobody reads."""
        drawn = drawn_keys("ui.cards.js", "gateActions", "cardItems", "phoneSplit",
                           "phoneActions", "backlogActions", "putCi", "putWorker", "putNamed")
        # c-600: the shipping phase draws its own (app/ui.shipping.js)
        drawn |= {"next-front", "next-filing"} | drawn_keys("ui.shipping.js", "gateItems", "cardItems", "waysIn", "handItems")
        self.assertEqual(sorted(tip_keys() - drawn), [])


    def test_an_adapter_verb_s_line_is_its_own_help(self):
        """The adapter's vocabulary stays in its pack: the deck reads the verb's
        `help`, and the table holds only the fallback."""
        body = js_function("ui.tips.js", "verbTip")
        self.assertIn("v.help", body)


def joined(text: str) -> str:
    """The table's strings with their `' +` continuations joined, as the page sees them."""
    return re.sub(r"'\s*\+\s*\n\s*'", "", text)


class AReviewCardsActionsTest(unittest.TestCase):
    """2026-09-24: a review card's actions make sense for a review. The pane's drawing is
    `tests/fixtures/deck-pane.js` (RV-3); these hold the words and the guards in place."""


    def test_a_review_card_is_never_split(self):
        body = js_function("ui.cards.js", "gateActions")
        line = next(l for l in body.splitlines() if "K.stageOf(c) !== 'done'" in l)
        self.assertIn("!c.derived.review", line)

    def test_its_house_actions_are_drawn_only_while_it_reviews(self):
        self.assertIn("c.derived.review === 'reviewing'", js_function("ui.cards.js", "houseActs"))
        body = js_function("ui.cards.js", "cardItems")
        for key in ("talk-voice", "resume-house", "resume-app", "dropin"):
            line = next(l for l in body.splitlines() if f"put('{key}'" in l)
            self.assertIn("live", line, key)

    def test_a_review_card_has_no_edit_and_review_settings_in_its_place(self):
        """His call, 2026-09-24: the generic Edit opened a house card's form, whose fields a
        review card takes from its pull request."""
        gate = js_function("ui.cards.js", "gateActions")
        line = next(l for l in gate.splitlines() if "put('edit'" in l)
        self.assertIn("!c.derived.review", line)
        body = js_function("ui.cards.js", "cardItems")
        line = next(l for l in body.splitlines() if "put('review-settings'" in l)
        self.assertIn("reviewSettable(c)", line)
        settable = js_function("ui.cards.js", "reviewSettable")
        for word in ("'waiting'", "'posted'", "'new'", "c.stage === 'assigned'", "!c.session_id"):
            self.assertIn(word, settable)
        self.assertIn("'review-settings'", js_function("ui.tips.js", "cardOrder") + source("ui.tips.js"))

    def test_the_settings_sheet_writes_the_model_and_the_focus(self):
        body = js_function("ui.reviews.js", "settingsBody")
        self.assertIn("model: s.model", body)
        self.assertIn("'options.review_focus'", body)


class HeldInATerminalTest(unittest.TestCase):
    """The deck half of U3: a card he dropped into shows it, and draws no resume."""

    def test_the_pill_and_the_absent_resumes(self):
        body = js_function("ui.cards.js", "cardItems")
        self.assertIn("put('in-terminal'", body)
        line = next(l for l in body.splitlines() if "put('resume-house'" in l)
        self.assertIn("!K.inTerminal(c)", line)
        gate = js_function("ui.cards.js", "gateActions")
        self.assertIn("held = K.inTerminal(c)", gate)
        self.assertIn("if (!held && c.session_id) put('resume'", gate)
        self.assertIn("if (c.session_id && !held) put('answer'", gate)

    def test_a_terminal_session_in_the_listing_counts_too(self):
        """Found on the scratch deck: the listing's interactive row read as a house, so Drop
        in said "attach" and Logs and Stop were drawn, all three taking a background id."""
        self.assertIn("kind === 'interactive'", js_function("ui.tips.js", "inTerminal"))
        body = js_function("ui.cards.js", "cardItems")
        self.assertIn("if (K.houseOf(c) && K.houseOf(c).recorded !== false && !K.inTerminal(c)) {", body)
        self.assertIn("already open in your terminal", joined(source("ui.tips.js")))


    def test_the_hold_is_read_the_way_the_server_reads_it(self):
        body = js_function("ui.tips.js", "inTerminal")
        self.assertIn("dropin_hold", body)
        self.assertIn(".seen", body)
        self.assertIn(".until", body)


if __name__ == "__main__":
    unittest.main()
