"""The owner-words guard (`tests/owner_words.py`, c-699): what Shipyard says calls its user
"the user", and a new sentence that says "he" fails `make drift`, so `make test`."""

import tempfile
import unittest
from pathlib import Path

from keel import console, consolehandoff
from tests import owner_words


def tree(files: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="owner-words-"))
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


class TreeTest(unittest.TestCase):
    def test_nothing_shipyard_says_calls_its_user_he(self):
        found, _ = owner_words.hits()
        self.assertEqual(found, [], "say the user, you or they:\n" + "\n".join(found))

    def test_every_table_entry_still_matches_something(self):
        _, unused = owner_words.hits()
        self.assertEqual(unused, [], "\n".join(unused))


class PromptTest(unittest.TestCase):
    """c-731: what Keel types into Bosun's session, and the note it hands a compaction."""

    def test_no_prompt_keel_types_to_bosun_calls_the_user_he(self):
        for prompt in (console.START_PROMPT, console.RESUME_PROMPT, consolehandoff.INSTRUCTIONS):
            self.assertFalse(owner_words.flagged(prompt), prompt)

    def test_a_module_that_types_a_prompt_never_waits_whole(self):
        """A whole-file entry would let a new prompt there say "he" unseen."""
        whole = [where for where, piece, _ in owner_words.WAITING
                 if where in owner_words.PROMPTERS and piece == "*"]
        self.assertEqual(whole, [])


class ScratchTest(unittest.TestCase):
    def test_a_new_engine_sentence_that_says_he_is_a_hit(self):
        root = tree({"keel/gate.py": 'def refuse(card):\n    raise ValueError(f"{card} waits at his gate")\n'})
        found, _ = owner_words.hits(root, tables=[])
        self.assertEqual(found, ["keel/gate.py:2: waits at his gate"])

    def test_a_comment_and_a_docstring_are_not_what_is_said(self):
        root = tree({"keel/gate.py": '"""His gate (c-1)."""\n\n# he taps it\nKIND = "his"\n',
                     "app/ui.gate.js": "/* he taps it */\nvar kind = row.his ? ' his' : '';\n"})
        self.assertEqual(owner_words.hits(root, tables=[]), ([], []))

    def test_shipped_text_is_read_line_by_line(self):
        root = tree({"etc/house-contract.md": "# The house\n\nShort notes for him go on the card.\n",
                     "etc/shipyard.example.toml": "hold = 300   # after his last sentence\n"})
        found, _ = owner_words.hits(root, tables=[])
        self.assertEqual([hit.split(":")[0] for hit in found],
                         ["etc/house-contract.md", "etc/shipyard.example.toml"])

    def test_the_voice_service_is_read_and_a_new_sentence_of_its_is_a_hit(self):
        """c-699 review F2: the voice service says what the user hears. Its standing
        sentences wait in the table one by one, so a new one fails."""
        root = tree({"voice/harbor_voice/filler.py": 'LINES = ("One moment for him.", "Asking the house.")\n'})
        found, _ = owner_words.hits(root, tables=[])
        self.assertEqual(found, ["voice/harbor_voice/filler.py:1: One moment for him."])

    def test_no_voice_sentence_waits(self):
        """c-722: the voice service's sentences say "the user", so none is left in the table."""
        self.assertEqual([where for where, _, _ in owner_words.WAITING if where.startswith("voice/")], [])

    def test_a_table_entry_lets_its_piece_through_and_fails_once_it_matches_nothing(self):
        root = tree({"keel/gate.py": 'PATTERN = "(the|his) board"\n'})
        entry = ("keel/gate.py", "(the|his)", "a pattern")
        self.assertEqual(owner_words.hits(root, tables=[entry]), ([], []))
        stale = ("keel/gone.py", "*", "a file that left")
        self.assertEqual(owner_words.hits(root, tables=[entry, stale])[1],
                         ["keel/gone.py | * matches nothing"])

    def test_the_words_and_what_is_not_one(self):
        for text in ("only his Ship pushes", "He said:", "waiting on him", "he's away",
                     "wrote these himself", "HE CHOSE the first"):
            self.assertTrue(owner_words.flagged(text), text)
        for text in ("his", " him", "{his}", "the user said", "the history", "this", "she",
                     "ahead of them", "they keep", "help", "The checkout"):
            self.assertFalse(owner_words.flagged(text), text)


if __name__ == "__main__":
    unittest.main()
