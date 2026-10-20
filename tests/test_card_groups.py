"""V2-1 and V2-3: every card action sits in exactly one group, from ONE table.

"If we have hundreds of options it becomes hard to find the item" (2026-09-24). The card's
actions come in groups (`GROUPS` in `app/ui.tips.js`): Decide, Continue, Talk to it, Pages
and Links (c-644: Read was both), the flow's own (one per `group` its moves name), and Card. These are greps over the page's source, as `tests/test_card_tips.py` is: what
the renderers actually DRAW (the group's button, the menu, the line under each name, the
phone's sheet under the same headings) is `tests/fixtures/deck-pane.js`, run by
`tests/test_deck_pane.py`.
"""

import re
import unittest
from pathlib import Path

from tests.test_card_tips import drawn_keys, source, tip_keys
from tests.test_deck_css import js_function

STATUS_KEYS = {"on-voice", "in-terminal", "ship-why", "need-codehost", "need-tracker",
               "ship-prepared"}      # a fact about the card, drawn before the groups (ship-prepared: c-723)
NOT_ACTIONS = STATUS_KEYS | {"more"}           # the phone's overflow opens the rest


def groups() -> dict[str, list[str]]:
    """{group key: [action keys]} read from the GROUPS table's own block."""
    text = source("ui.tips.js")
    block = text[text.index("var GROUPS = ["):]
    block = block[:block.index("];") + 2]
    out = {}
    for key, keys in re.findall(r"key: '([a-z]+)', name: '[^']+',\s*keys: \[([^\]]*)\]", block, re.S):
        out[key] = re.findall(r"'([a-z-]+)'", keys)
    return out


def every_drawn_key() -> set[str]:
    cards = drawn_keys("ui.cards.js", "gateActions", "cardItems", "phoneSplit", "phoneActions",
                       "backlogActions", "putCi", "putWorker", "putNamed")      # putCi: c-642; putWorker: c-645; putNamed: c-719
    tile = set(re.findall(r"keyed\('([a-z-]+)'", js_function("ui.views.js", "houseActionNodes")))
    shipping = drawn_keys("ui.shipping.js", "gateItems", "cardItems", "waysIn", "handItems")      # c-600, c-653, c-655
    return cards | tile | shipping | {"next-front", "next-filing"}


class OneGroupEachTest(unittest.TestCase):

    def test_every_drawn_key_is_in_exactly_one_group(self):
        table = groups()
        for key in sorted(every_drawn_key() - NOT_ACTIONS):
            homes = [g for g, keys in table.items() if key in keys]
            self.assertEqual(len(homes), 1, f"{key} is in {homes or 'no group'}")

    def test_no_group_names_an_action_nothing_draws(self):
        drawn = every_drawn_key() | {"assign-tree"}
        for group, keys in groups().items():
            for key in keys:
                self.assertIn(key, drawn, f"{group} lists {key}, which nothing draws")


class TheMenuIsARealMenuTest(unittest.TestCase):
    def test_the_caret_and_the_menu_carry_their_roles(self):
        body = js_function("ui.core.js", "splitButton")
        for needle in ("'aria-haspopup': 'menu'", "'aria-expanded'", "role: 'menu'", "onkeydown: menuKeys",
                       "onkeydown: caretKeys(o.id)"):
            self.assertIn(needle, body)
        self.assertIn("'menuitem'", body)

    def test_the_keys(self):
        body = js_function("ui.core.js", "menuKeys")
        for key in ("Escape", "Tab", "Home", "End"):
            self.assertIn(f"'{key}'", body)
        self.assertIn("ArrowDown: 1, ArrowUp: -1", source("ui.core.js"))

    def test_escape_puts_focus_back_on_the_caret(self):
        self.assertIn("closeMenu(true)", js_function("ui.core.js", "menuKeys"))
        self.assertIn("caret.focus()", js_function("ui.core.js", "closeMenu"))

    def test_the_page_s_own_escape_closes_the_menu_first(self):
        text = source("ui.core.js")
        handler = text[text.index("/* Escape closes what is open, innermost first. */"):]
        self.assertLess(handler.index("if (App.menu)"), handler.index("if (App.modal)"))


if __name__ == "__main__":
    unittest.main()
