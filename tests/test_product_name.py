"""The product's name (c-699, c-672's name decision): what a user sees says Shipyard.

`keel` stays the engine's package, its commands and its `KEEL_*` variables, and a session is
still told "Keel" beside them. The deck is all user: its title, its installed name, and every
string literal of `app/*.js` say Shipyard. `KEPT` names the literals that say Keel on purpose;
an entry that matches nothing fails.

The packs that ship (`PACKS`) are held the same way (review F3): every string of a manifest
(a pack's description and its fixes are setup text) and every string literal of the pack's
code, with `KEPT_PACKS` for what a house reads. The employer's pack is not read here."""

import json
import re
import tomllib
import unittest
from pathlib import Path

from tests import nouns

ROOT = Path(__file__).resolve().parent.parent
OLD = re.compile(r"\bKeel\b")
ESCAPE = re.compile(r"\\[ntr]")    # a literal is read raw: `\\nKeel` must not hide the word
PACKS = ("sandbox", "github", "gitea")      # the packs that ship; the employer's pack is its own
KIT = "keel/packkit"               # what every pack on the kit says (c-735)
# `(file, piece, why)`: a card on the engine's own repo is a Keel card, by that repo's name.
KEPT = [
    ("app/ui.cards.js", "a Keel card: Bosun builds it", "the chip of a card on the engine's own repo"),
    ("app/ui.cards.js", "Keel \\u00b7 Bosun", "the same chip's words"),
]
# What a shipped pack says to a HOUSE keeps Keel, as every session's text does.
HOUSE = "a house reads it, beside the keel commands it runs"
KEPT_PACKS = [
    ("packs/sandbox/sb_brief.py", "Keel tells you reviewers' comments", HOUSE),
    ("keel/packkit/brief.py", "Keel tells you reviewers' comments", HOUSE),
    ("keel/packkit/guard.py", "is Approve outcome's, which Keel runs itself: a house never", HOUSE),
    ("keel/packkit/guard.py", "ready is Approve outcome's, which Keel runs itself: this", HOUSE),
]


def says_keel(text: str) -> bool:
    return bool(OLD.search(ESCAPE.sub(" ", text)))


def manifest_strings(value, key: str = "") -> list[tuple[str, str]]:
    """`(key, text)` for every string a manifest holds, whatever its depth."""
    if isinstance(value, dict):
        return [found for name, inner in value.items() for found in manifest_strings(inner, f"{key}.{name}".strip("."))]
    if isinstance(value, list):
        return [found for inner in value for found in manifest_strings(inner, key)]
    return [(key, value)] if isinstance(value, str) else []


def pack_text(root: Path = ROOT) -> list[tuple[str, str, str]]:
    """`(file, where, text)` for what a shipped pack says: every string of its manifest
    (comments are not read), and every string literal of its code and of the kit's, which
    every pack on the kit says."""
    found = []
    for pack in PACKS:
        manifest = root / "packs" / pack / "pack.toml"
        found += [(manifest.relative_to(root).as_posix(), key, text)
                  for key, text in manifest_strings(tomllib.loads(manifest.read_text(encoding="utf-8")))]
        found += code_text(root, sorted((root / "packs" / pack).glob("*.py")))
    return found + code_text(root, sorted((root / KIT).glob("*.py")))


def code_text(root: Path, paths: list[Path]) -> list[tuple[str, str, str]]:
    return [(path.relative_to(root).as_posix(), str(line), text) for path in paths
            for line, text in nouns.python_literals(path.read_text(encoding="utf-8"))]


def deck_literals(root: Path = ROOT) -> list[tuple[str, int, str]]:
    return [(path.relative_to(root).as_posix(), line, text)
            for path in sorted((root / "app").glob("*.js"))
            for line, text in nouns.js_literals(path.read_text(encoding="utf-8"))]


class NameTest(unittest.TestCase):
    def test_the_page_and_the_installed_app_are_called_shipyard(self):
        self.assertIn("<title>Shipyard</title>", (ROOT / "app" / "index.html").read_text())
        manifest = json.loads((ROOT / "app" / "manifest.json").read_text())
        self.assertEqual((manifest["name"], manifest["short_name"]), ("Shipyard", "Shipyard"))
        self.assertEqual((ROOT / "README.md").read_text().splitlines()[0], "# Shipyard")

    def test_nothing_the_deck_says_calls_the_product_keel(self):
        used, said = set(), []
        for rel, line, text in deck_literals():
            if not says_keel(text):
                continue
            kept = next((index for index, (where, piece, _) in enumerate(KEPT)
                         if where == rel and piece in text), None)
            if kept is None:
                said.append(f"{rel}:{line}: {' '.join(text.split())[:120]}")
            else:
                used.add(kept)
        self.assertEqual(said, [], "the deck says Keel where a user reads Shipyard:\n" + "\n".join(said))
        self.assertEqual([KEPT[index][:2] for index in range(len(KEPT)) if index not in used], [],
                         "a KEPT entry matches nothing")

    def test_nothing_a_shipped_pack_tells_its_user_calls_the_product_keel(self):
        """c-699 review F3: a pack's manifest is setup text, and its code writes what the
        user reads (a pull request's body, a Ship refusal). A house's text is in the table."""
        used, said = set(), []
        for rel, where, text in pack_text():
            if not says_keel(text):
                continue
            kept = next((index for index, (name, piece, _) in enumerate(KEPT_PACKS)
                         if name == rel and piece in " ".join(text.split())), None)
            if kept is None:
                said.append(f"{rel} {where}: {' '.join(text.split())[:120]}")
            else:
                used.add(kept)
        self.assertEqual(said, [], "a shipped pack says Keel where a user reads Shipyard:\n" + "\n".join(said))
        self.assertEqual([KEPT_PACKS[index][:2] for index in range(len(KEPT_PACKS)) if index not in used], [],
                         "a KEPT_PACKS entry matches nothing")

    def test_a_word_after_an_escape_is_still_read(self):
        self.assertTrue(says_keel("\\n\\nKeel card c-1."))
        self.assertFalse(says_keel("the keel command, and KEEL_HOME"))


if __name__ == "__main__":
    unittest.main()
