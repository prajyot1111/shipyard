"""The space themes (work, personal, and the console since c-519): they must not drift from
the deck, from each other, or below the contrast floor.

`app/theme-work.css`, `app/theme-personal.css` and `app/theme-console.css` are what every
surface a house writes links, and they deliberately DUPLICATE the deck's palette: a plan is
a standalone file that has to render with no deck, no Tailwind and no DaisyUI, so it cannot
import `app/ui.css`. Duplication that nothing checks is duplication that drifts, so these
tests are the check:

1. **The palette is the deck's, token for token.** Every token of `html[data-mode="work"]`
   in `app/ui.css` has the same value in `app/theme-work.css`, and the same for personal and
   the console. A colour changed in one place and not the other fails here rather than on
   the human's screen six weeks later.
2. **The themes differ ONLY in the palette.** Everything after the shared marker is byte
   identical, so an element rule cannot be fixed in one space and left broken in another.
3. **Every text pair clears 4.5:1.** The pairs are the ones the stylesheet actually uses
   (ink on each surface, the muted ink, links, the status inks on their tints), measured
   with the WCAG formula rather than trusted. The floor is 4.5:1 for all of them: the
   biggest type here is 15px 600, which is not WCAG large text (that is 24px, or 18.66px
   bold), so nothing in these files may take the 3:1 allowance.
4. **The deck serves them.** Each is in `serve.APP_FILES`, so a surface opened through the
   deck's own origin can reach one.

The rendered proof, at 1440x900 and 390x844 in work and personal, is in `docs/deck-shots/`;
the console's is in c-519's outcome.
"""

import re
import unittest
from pathlib import Path

from keel import serve

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
SHARED_MARKER = "/* ===== shared:"
SPACES = ("work", "personal", "console")
FLOOR = 4.5

TOKEN = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;}]+)")
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def without_comments(text: str) -> str:
    return COMMENT.sub("", text)


def block(text: str, selector: str) -> str:
    """The body of the first `<selector>{...}` block, comments stripped."""
    start = text.index(selector + "{") + len(selector) + 1
    return without_comments(text[start:text.index("}", start)])


def tokens(body: str) -> dict[str, str]:
    return {name: value.strip() for name, value in TOKEN.findall(body)}


def theme(space: str) -> str:
    return (APP / f"theme-{space}.css").read_text()


def palette_of(space: str) -> dict[str, str]:
    """The theme's own `:root` palette: the first block, before the shared marker."""
    return tokens(block(theme(space).split(SHARED_MARKER)[0], ":root"))


def deck_palette(space: str) -> dict[str, str]:
    return tokens(block((APP / "ui.css").read_text(), f'html[data-mode="{space}"]'))


# ----- colour, measured rather than trusted -----

def channel(value: int) -> float:
    ratio = value / 255
    return ratio / 12.92 if ratio <= 0.04045 else ((ratio + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    raw = hex_colour.strip().lstrip("#")
    red, green, blue = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(one: str, two: str) -> float:
    first, second = sorted((luminance(one), luminance(two)), reverse=True)
    return (first + 0.05) / (second + 0.05)


# (ink token, background token): every pair the stylesheet puts text on.
TEXT_PAIRS = (
    ("ink", "canvas"), ("ink", "s1"), ("ink", "s2"), ("ink", "s3"),
    ("ink-2", "canvas"), ("ink-2", "s1"), ("ink-2", "s2"), ("ink-2", "s3"),
    ("accent-ink", "canvas"), ("accent-ink", "s1"), ("accent-ink", "accent-soft"),
    ("good", "canvas"), ("good", "s1"), ("good", "good-soft"),
    ("warn", "canvas"), ("warn", "s1"), ("warn", "warn-soft"),
    ("crit", "canvas"), ("crit", "s1"), ("crit", "crit-soft"),
)


class PaletteTest(unittest.TestCase):
    def test_the_theme_carries_the_decks_palette_token_for_token(self):
        for space in SPACES:
            deck, mine = deck_palette(space), palette_of(space)
            self.assertTrue(deck, f"no html[data-mode={space!r}] block in app/ui.css")
            wrong = {name: (value, mine.get(name)) for name, value in deck.items()
                     if mine.get(name) != value}
            self.assertEqual(wrong, {}, f"theme-{space}.css has drifted from app/ui.css "
                                        f"(token: ui.css value, theme value): {wrong}")

    def test_the_themes_carry_the_same_tokens(self):
        for space in SPACES[1:]:
            self.assertEqual(sorted(palette_of(SPACES[0])), sorted(palette_of(space)),
                             f"the {space} palette defines different tokens from work's")


class SharedTest(unittest.TestCase):
    def test_everything_but_the_palette_is_identical(self):
        parts = [theme(space).split(SHARED_MARKER) for space in SPACES]
        for space, split in zip(SPACES, parts):
            self.assertEqual(len(split), 2, f"theme-{space}.css has no shared marker")
        for space, split in zip(SPACES[1:], parts[1:]):
            self.assertEqual(parts[0][1], split[1],
                             f"the element rules of theme-{space}.css differ from work's; they "
                             f"are one stylesheet with a palette each, so a fix belongs in all")


class ContrastTest(unittest.TestCase):
    def test_every_text_pair_clears_the_floor(self):
        failures = []
        for space in SPACES:
            palette = palette_of(space)
            for ink, background in TEXT_PAIRS:
                ratio = contrast(palette[ink], palette[background])
                if ratio < FLOOR:
                    failures.append(f"{space}: --{ink} on --{background} is {ratio:.2f}:1")
        self.assertEqual(failures, [], f"below {FLOOR}:1: {failures}")


if __name__ == "__main__":
    unittest.main()
