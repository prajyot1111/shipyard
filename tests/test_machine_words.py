"""The machine-words guard (c-634, c-628 S6): on one machine nothing names a machine.

Shipyard runs on one machine. A sentence a user reads or hears there never says "the box",
"the Mac", "the laptop" or "the other machine": one machine is "this machine" when a sentence
needs a subject at all. This reads every string literal a user could end up reading, the
same way the noun guard does (`tests/nouns.py`: comments and docstrings are never literals,
and a bare identifier is a data key, which is how a board's `laptop` icon stays out), in
`app/*.js` and `keel/**/*.py`, plus every line of the shipped text a user reads as it is
(`etc/house-contract.md`, `etc/shipyard.example.toml`, each `packs/*/pack.toml`).

Two tables say what is left on purpose:

- `C622`: strings that only a second machine reaches, or that live in code c-622 deletes
  wholesale. c-622 empties this table as it deletes the code; an entry that matches nothing
  fails, so the table cannot outlive what it names.
- `NOT_MACHINES`: a line that says one of the words and does not mean a machine (empty
  since the board's icon names left the house contract for the generated brief, c-603).

Each entry is `(path, piece, why)`: `piece` is a piece of the flagged text, or `*` for the
whole file.
"""

import re
import unittest
from pathlib import Path

from tests import nouns

ROOT = Path(__file__).resolve().parent.parent
WORDS = re.compile(r"(?i:\bthe box\b|\bbox's\b|\bbox home\b|<box>|\blaptops?\b|\bkeel-box\b"
                   r"|\b(?:an)?other machine'?s?\b|\bboth machines\b)|\bMac'?s?\b")
TEXTS = ("etc/house-contract.md", "etc/shipyard.example.toml")

C622 = []

NOT_MACHINES: list = []


def literals(path: Path) -> list[tuple[int, str]]:
    """`(line, text)` for each piece of text a user could read in `path`."""
    source = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        return nouns.js_literals(source)
    if path.suffix == ".py":
        return nouns.python_literals(source)
    return list(enumerate(source.splitlines(), 1))


def sources(root: Path = ROOT) -> list[Path]:
    return [*nouns.sources(root), *(root / name for name in TEXTS if (root / name).exists()),
            *sorted(root.glob("packs/*/pack.toml"))]


def flagged(text: str) -> bool:
    return not nouns.IDENTIFIER.match(text) and bool(WORDS.search(text))


def hits(root: Path = ROOT, tables: list | None = None) -> tuple[list[str], list[str]]:
    """`(hits, unused)`: each flagged text outside the tables as `path:line: text`, and each
    table entry that matched nothing."""
    tables = C622 + NOT_MACHINES if tables is None else tables
    used, found = set(), []
    for path in sources(root):
        rel = path.relative_to(root).as_posix()
        for line, text in literals(path):
            if not flagged(text):
                continue
            match = next((index for index, (where, piece, _) in enumerate(tables)
                          if where == rel and (piece == "*" or piece in text)), None)
            if match is None:
                found.append(f"{rel}:{line}: {' '.join(text.split())[:160]}")
            else:
                used.add(match)
    unused = [f"{where} | {piece} matches nothing"
              for index, (where, piece, _) in enumerate(tables) if index not in used]
    return found, unused


class MachineWordsTest(unittest.TestCase):
    def test_nothing_a_user_reads_on_one_machine_names_a_machine(self):
        found, _ = hits()
        self.assertEqual(found, [], "a machine named in a user's words; say it without one, or, "
                         "if only a second machine reaches it, add it to C622:\n" + "\n".join(found))

    def test_every_table_entry_still_matches_something(self):
        _, unused = hits()
        self.assertEqual(unused, [], "\n".join(unused))

    def test_the_words_and_what_is_not_one(self):
        for said in ("the box deploys", "from the Mac.", "on his laptop", "ssh -t keel-box x",
                     "the other machine", "once both machines run it", "the Mac's drain",
                     "Option paths on a box home", "imported: <box>"):
            self.assertTrue(flagged(said), said)
        for said in ("laptop", "box", "box-shadow: none", "macOS", "a message box", "this machine",
                     "the checkbox"):
            self.assertFalse(flagged(said), said)


if __name__ == "__main__":
    unittest.main()
