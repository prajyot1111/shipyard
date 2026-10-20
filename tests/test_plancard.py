"""The plan format card (P4-1): generated from the parser and the lint, held equal to them.

A house is given this card in its brief. A block kind the parser learns, a section the lint
starts requiring or a rule it starts refusing, without its line on the card, is a card that
lies to every house started after it; this suite is what fails first.
"""

import tempfile
import unittest
from pathlib import Path

from keel import plancard, planblocks, planformat, planlint

ROOT = Path(__file__).resolve().parent.parent


class CardTest(unittest.TestCase):
    def test_every_block_kind_the_parser_knows_has_its_line(self):
        self.assertEqual(set(plancard.SIGNATURES), set(planblocks.KINDS))
        card = plancard.format_card()
        for kind in planblocks.KINDS:
            head = plancard.SIGNATURES[kind][0]
            self.assertIn(f"  {head}", card, f"{kind} is not on the card")

    def test_every_rule_a_mechanism_holds_is_on_the_card_and_no_other(self):
        held = {rule for rule, how in planlint.ENFORCED.items() if how.startswith("M")}
        self.assertEqual(set(plancard.RULES), held)
        card = plancard.format_card()
        for rule in held:
            self.assertRegex(card, rf"(?m)^  {rule}\b")

    def test_the_sections_are_the_lints_own_in_its_order(self):
        card = plancard.format_card()
        order = ", ".join(planlint.TITLE_OF[n] for n in planlint.PLAN_ORDER)
        self.assertIn(order, card)
        self.assertIn(", ".join(planlint.TITLE_OF[n] for n in planlint.OUTCOME_SECTIONS), card)
        for title in (planlint.TITLE_OF[n] for n in planlint.PLAN_ORDER):
            self.assertIn(title.lower(), planformat.NAME_OF, f"{title} is a heading the parser names")

    def test_the_vocabularies_and_the_limits_are_the_parsers(self):
        card = plancard.format_card()
        self.assertIn("|".join(planblocks.STEP_STATES), card)
        self.assertIn("|".join(planblocks.TONES), card)
        self.assertIn("|".join(planformat.CALLOUT_TONES), card)
        self.assertIn("|".join(planblocks.FRAMES), card)
        self.assertIn(f"2 to {planblocks.MAX_OPTIONS}", card)
        self.assertIn(f"at most {planlint.SUMMARY_WORDS} words", card)
        self.assertIn(f"v{planformat.VERSION}", card)


    def test_the_frontmatter_on_the_card_parses_as_the_format(self):
        """The skeleton the card shows is what marks a file as the format."""
        card = plancard.format_card()
        skeleton = card[card.index("---"):card.index("---", card.index("---") + 3) + 3]
        doc = planformat.parse(skeleton + "\n# t\n", "plan.md")
        self.assertTrue(doc["format"])
        self.assertEqual(doc["kind"], "plan")


class CopyTest(unittest.TestCase):
    def test_every_copy_embeds_the_current_card(self):
        card = plancard.format_card()
        for relative in plancard.COPIES:
            embedded = plancard.embedded((ROOT / relative).read_text())
            self.assertIsNotNone(embedded, f"{relative} has no ```{plancard.FENCE_LANG} block")
            self.assertEqual(embedded, card, f"{relative} is stale: run python3 -m keel.plancard --write")

    def test_write_rewrites_a_stale_copy_and_leaves_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.md"
            path.write_text(f"before\n\n```{plancard.FENCE_LANG}\nold\n```\n\nafter\n")
            self.assertTrue(plancard.write_copy(path))
            text = path.read_text()
            self.assertEqual(plancard.embedded(text), plancard.format_card())
            self.assertTrue(text.startswith("before\n") and text.endswith("after\n"))
            self.assertFalse(plancard.write_copy(path))


if __name__ == "__main__":
    unittest.main()
