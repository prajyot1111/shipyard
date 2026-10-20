"""The deck's page: the rules a future edit must not quietly drop.

The surface the page decides is only ever looked at by a human with a browser. That is how a
phone audit signed off on "overflow=0" while the Atlas route painted 8592px of document below
the border drawn around it (`<install>/history/docs/deck-mobile-audit.md`, 2026-09-18).

The render is still the proof: `<install>/history/tests/live_deck.md` records the sweep, and nothing here can
replace it. These are greps, deliberately: a stdlib suite cannot lay out CSS or run the
page's JavaScript, and a test that pretended to would be worse than one that says plainly
what it is checking for. `js_function` is the one reader the other deck tests share.

1. The page CHANGES rather than reloads: the render pass morphs, rows are keyed, handlers
   are carried, and the patches that used to put back what a rebuild ate are gone.
2. A gate is answered in a field he can see what he typed in, with the draft kept off the
   DOM so nothing that redraws can eat it.
3. Approve outcome is not drawn while it lands, Rotate follows Resume's rule, and the tree's
   confirm sends the ids its preview showed.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def js_function(module: str, name: str) -> str:
    """One `function <name>(...) {...}` body from an `app/` module, braces counted.

    Counted rather than matched: a body holds braces of its own, and a regex cannot see
    where the function ends.
    """
    text = (APP / module).read_text(encoding="utf-8")
    found = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", text)
    assert found, f"{module} has no function {name}"
    depth, i = 1, found.end()
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[found.end():i - 1]


class ThePageChangesRatherThanReloads(unittest.TestCase):
    """The body was emptied and rebuilt whole every five seconds.

    Everything the DOM held went with it (the scroll offsets, the caret, the selection, a
    transition part way through, an SVG's transform), and each kind got a patch of its own
    to put it back: a scroll map in sessionStorage, `focusMark`/`focusRestore`, a node cache
    keyed and hashed per pane section. The render pass MORPHS now (`K.morph`), so all of
    that survives by construction, and the patches are gone.

    The morph's own behaviour is checked by running it, under node, against a DOM stand-in:
    `tests/fixtures/deck-morph.js`, run from tests/test_serve.py. What is held here is that
    the page actually goes through it and that the patches did not quietly come back.
    """

    def core(self) -> str:
        return (APP / "ui.core.js").read_text(encoding="utf-8")


    def test_every_surface_the_page_draws_goes_through_it(self):
        """A surface that still emptied its host would be the old defect in one place."""
        for module, name in (("ui.js", "renderBody"), ("ui.core.js", "renderSheet"),
                             ("ui.modal.js", "renderModal")):
            body = js_function(module, name)
            self.assertIn("paint('", body, f"{module} {name} does not morph into its host")
            self.assertNotIn("innerHTML = ''", body, f"{module} {name} still empties its host")
        for name in ("renderRail", "renderHeader", "renderControls", "renderDock"):
            self.assertIn("paint(", js_function("ui.core.js", name), f"{name} does not morph")


    def test_a_handler_is_a_property_so_the_morph_can_carry_it(self):
        """addEventListener cannot be read back off a node, so a kept node would keep
        acting on the card last pass built it from."""
        body = js_function("ui.core.js", "el").replace(" ", "")
        self.assertNotIn("addEventListener", body, "K.el still binds handlers it cannot carry")
        self.assertIn("node._on", body, "K.el does not record its handlers for the morph")

    def test_the_rows_a_list_reorders_are_keyed(self):
        """Unkeyed, a re-sort walks every row into the one above it."""
        for module, name, key in (("ui.cards.js", "cardRow", "'data-key': c.id"),
                                  ("ui.cards.js", "kanbanTile", "'data-key': c.id"),
                                  ("ui.views.js", "houseTile", "'data-key': c.id"),
                                  ("ui.views.js", "attentionRow", "'data-key': c.id"),
                                  ("ui.reviews.js", "reviewRow", "'data-key': c.id")):
            self.assertIn(key, js_function(module, name), f"{name} draws unkeyed rows")


    def test_a_cards_pane_lists_every_board_it_has(self):
        """A card has as many boards as it has pictures, so the pane is a list with the
        live one marked, not one board and a count."""
        block = js_function("ui.cards.js", "boardBlock")
        self.assertIn("b.boards", block, "the pane still reads one board")
        self.assertIn("rows.map(", block)
        self.assertIn("'data-key': b.id", js_function("ui.cards.js", "boardRow"),
                      "the rows are unkeyed, so a new board walks them")


    def test_a_tick_re_renders_and_never_fetches(self):
        """`state` is the document moving and `tick` is fifteen seconds passing. Answering
        the second with a fetch is what had an idle deck pull `/api/state` four times a
        minute to move some ages."""
        heard = js_function("ui.core.js", "heard")
        self.assertIn("'tick'", heard, "the page does not know the tick line")
        # The Console alone fetches on a tick (c-519): Bosun's status arrives with the Mac's
        # push, which writes nothing on the board. Every other view only re-renders.
        console, rest = heard.split("if (bits[0] === 'tick') {", 1)
        self.assertIn("App.view === 'console'", console.rsplit("\n", 2)[-2])
        tick = rest.split("return;", 1)[0]
        self.assertIn("K.render()", tick)
        self.assertNotIn("load(", tick, "a tick still costs a fetch")


class AGateIsAnsweredInAFieldHeCanRead(unittest.TestCase):
    """The reason was typed into a one-line input where Enter submitted.

    On the phone he could see about thirty characters of what he had typed, and there was
    no way at all to say something WITH an Approve: answering a markdown plan's open
    questions cost a send back and then a second approve. One field answers all three now
    (Approve with a note, Send back, Send back and stay), in the deck's own sheet.
    """

    def cards(self) -> str:
        return (APP / "ui.cards.js").read_text(encoding="utf-8")


    def test_the_draft_lives_off_the_dom_and_only_a_submit_clears_it(self):
        """The poll rebuilds the body and `repaint` rebuilds the sheet, and the DOM is what
        a rebuild throws away."""
        core = (APP / "ui.core.js").read_text(encoding="utf-8")
        for name in ("K.draft =", "K.setDraft =", "K.clearDraft ="):
            self.assertIn(name, core, f"ui.core.js does not export {name}")
        self.assertIn("sessionStorage", js_function("ui.core.js", "setDraft"),
                      "a draft does not survive the page being reloaded")
        self.assertIn("K.clearDraft(", js_function("ui.cards.js", "submitSay"))
        self.assertNotIn("K.clearDraft(", js_function("ui.cards.js", "closeSay"),
                         "closing the field throws away what he typed")


class TheOutcomeSaysWhereTheLandingIs(unittest.TestCase):
    """E5: a queued Approve outcome is landing, testing, landed or refused on the card, and
    the gate row does not offer a second tap while it is under way."""


    def test_approve_outcome_is_not_drawn_while_it_lands(self):
        self.assertIn("!landingPending(c)", js_function("ui.cards.js", "gateActions"))


class RotateIsHisButton(unittest.TestCase):
    """R6: a Rotate session button beside Resume house, under the same rule, and the house
    word says rotating while the checkpoint turn runs."""

    def test_the_button_follows_resume_s_rule_and_is_absent_while_rotating(self):
        body = js_function("ui.cards.js", "cardItems")
        self.assertIn("'house.rotate'", body)
        self.assertIn("rotateOn() &&", body, "the button is drawn only with [keel] rotate on")
        self.assertIn("!rotatingOf(c)", body)


class TheTreeOnTheDeck(unittest.TestCase):
    """c-302: a big card opens on its tree, and the deck works none of it out itself.

    The outline is `derived.tree` and the order is the document's `queue`, both computed in
    `keel/tree.py`, so the deck, `kb tree`, `kb queue`, voice and the drain cannot tell him
    two orders. On the phone the tree is the first screen, above every button: before, the
    slices sat below six buttons, the plan and the brief (c-277, 2026-09-21).
    """


    def test_the_confirm_sends_the_ids_the_preview_showed(self):
        body = js_function("ui.tree.js", "assignSheet")
        self.assertIn("ids: p.assigned", body, "the confirm would assign whatever is there now")


if __name__ == "__main__":
    unittest.main()
