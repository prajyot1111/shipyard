"""The owner-words guard (c-699, c-672 step 7): what Shipyard says calls its user "the user".

Shipyard is one user's install, and whoever that is, the engine does not know them. A
sentence it says (to a house, to Bosun, on the deck, in a refusal, a note, a prompt or a
brief) says "the user", "you" or "they", never "he", "his" or "him". This reads what is SAID,
never a comment or a docstring (`tests/nouns.py` reads the literals, and a bare identifier
such as the item kind `his` is a data key, with or without a space around it), in the
places `LITERALS` and `TEXTS` name, and nowhere else:

- every string literal of `app/*.js`, `keel/**/*.py` and `etc/flows/*.toml` (the noun
  guard's own list), of the guard scripts a session is refused by, of the two packs that
  ship (`PACKS`), and of the voice service (`VOICE`), whose sentences the user hears;
- every line of the shipped text a session or a user reads as it is: the house contracts,
  the space contracts, the personal pipeline, the example config, the CLAUDE.md tier
  templates, the shipped packs' manifests, the memory and identity templates
  (`templates/`), and the README and the contributing guide.

Two tables say what is left on purpose, each entry `(path, piece, why)`, `piece` a piece of
the flagged text or `*` for the whole file. An entry that matches nothing fails, so neither
table outlives what it names.

- `WAITING`: text this guard would change and a builder may not: a file under the authority
  guard, or text the owner's memory embeds. Each leaves with the card that owns it (one
  owner's own text left the tree in c-722 landing B, and its entries with it). The voice service waits for nothing (c-722), so a new sentence there fails.
  The modules that type a prompt into Bosun's session (`PROMPTERS`) never wait whole
  (c-731): a refusal of theirs waits by its own sentence, so a prompt that says "he" fails.
- `NOT_THE_USER`: the word is not a sentence about the user (a class name, a pattern that
  reads what was heard or recorded).

Run as `python3 -m tests.owner_words` (`make drift` does): it prints each hit as
`path:line: text` and exits 1, or exits 0 silently.
"""

import re
import sys
from pathlib import Path

from tests import nouns

ROOT = Path(__file__).resolve().parent.parent
WORDS = re.compile(r"\b(?:he|him|his|himself|he's|he'd|he'll)\b", re.I)
FIELD = re.compile(r"\{[A-Za-z_][\w.]*\}")      # a format field names data, not a person
PACKS = ("sandbox", "github", "gitea")
SCRIPTS = ("bin/keel-house-guard", "bin/keel-builder-guard", "bin/keel-board-fence",
           "bin/keel-git-gate", "bin/keel-git-receive")
VOICE = "voice/harbor_voice/*.py"
LITERALS = (*SCRIPTS, *(f"packs/{pack}/*.py" for pack in PACKS), VOICE)
TEXTS = ("etc/house-contract.md", "etc/house-contract-drop.md", "etc/pipeline-personal.md",
         "etc/space-personal.md", "etc/space-work.md", "etc/shipyard.example.toml",
         "etc/claude-md/*.md", "templates/memory/*/*.md", "templates/identity/*.md",
         "README.md", "CONTRIBUTING.md",
         *(f"packs/{pack}/pack.toml" for pack in PACKS))

GUARDED = "under the authority guard: its wording changes on the user's own card"
# The modules that type a prompt into Bosun's session never wait whole (c-731): what they
# type says "the user", and only a refusal there waits, sentence by sentence.
PROMPTERS = ("keel/console.py", "keel/consolehandoff.py", "keel/consoletaps.py")
REFUSAL = "a refusal " + GUARDED
# The voice service is read sentence by sentence (c-699 review F2), and since c-722 none of
# its sentences waits: a new one fails.
WAITING = [
    ("keel/authority.py", "*", GUARDED),
    ("keel/console.py", "changing it is a personal card he", REFUSAL),
    ("keel/console.py", "Bosun's lifecycle is his tap", REFUSAL),
    ("keel/repair.py", "*", GUARDED),
    ("keel/repairhouse.py", "*", GUARDED),
    ("keel/boardgrammar.py", "what he hears in its place",
     "the grammar card, which the talker's memory in the install embeds word for word: its "
     "wording changes on a card that rewrites that copy too (`boardgrammar.write_all`), which "
     "writes into the owner's install, so a builder of the code does not change it alone"),
]
NOT_THE_USER = [
    ("app/ui.settings.js", ".who.him{", "a class name in the deck's own style sheet"),
    ("app/ui.shipsendback.js", "shiprow his", "a class name"),
    ("keel/boardpen.py", "|his|my)", "a pattern over what a session wrote, not a sentence"),
    ("keel/review/gate.py", "He sent the ",
     "a pattern over notes recorded before the wording changed, beside the new one"),
    ("voice/harbor_voice/filler.py", "\\b(?:the|its|his|her|your|my)\\s+fi",
     "a pattern over what was heard or drafted, not a sentence"),
    ("voice/harbor_voice/filler.py", "\\b(?:when|once|after|as soon as)\\s",
     "a pattern over what was heard or drafted, not a sentence"),
]


def said(path: Path, lines: bool) -> list[tuple[int, str]]:
    """`(line, text)` for each piece of text `path` says: its lines, or its literals."""
    source = path.read_text(encoding="utf-8")
    if lines:
        return list(enumerate(source.splitlines(), 1))
    return nouns.READERS.get(path.suffix, nouns.python_literals)(source)   # a bin/ script is Python


def sources(root: Path = ROOT) -> list[tuple[Path, bool]]:
    """Each file read, with whether it is read by line (shipped text) or by literal (code)."""
    found = [(path, False) for path in nouns.sources(root)]
    for patterns, lines in ((LITERALS, False), (TEXTS, True)):
        for pattern in patterns:
            found += [(path, lines) for path in sorted(root.glob(pattern)) if path.is_file()]
    return found


ESCAPE = re.compile(r"\\[ntr]")    # a literal is read raw: `\nhe` must not hide the word


def flagged(text: str) -> bool:
    plain = ESCAPE.sub(" ", FIELD.sub(" ", text))
    return not nouns.IDENTIFIER.match(text.strip()) and bool(WORDS.search(plain))


def hits(root: Path = ROOT, tables: list | None = None) -> tuple[list[str], list[str]]:
    """`(hits, unused)`: each flagged text outside the tables as `path:line: text`, and each
    table entry that matched nothing."""
    tables = WAITING + NOT_THE_USER if tables is None else tables
    used, found = set(), []
    for path, lines in sources(root):
        rel = path.relative_to(root).as_posix()
        for line, text in said(path, lines):
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


def main() -> int:
    found, unused = hits()
    if found:
        print(f"owner words: {len(found)} sentence(s) Shipyard says call its user he, his or "
              f"him; say the user, you or they:")
        print("\n".join(found))
    if unused:
        print("owner words: a table entry in tests/owner_words.py matches nothing:")
        print("\n".join(unused))
    return 1 if found or unused else 0


if __name__ == "__main__":
    sys.exit(main())
