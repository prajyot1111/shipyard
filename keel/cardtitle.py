"""A short title for a card filed from the user's own words (c-729).

The stranger run filed its first card with the whole sentence as the title ("In notes-api add
a way to delete a note"), and the branch, the list and the merge subject on main all carried
it. A title is what those can carry; the words themselves are kept, as the brief.

`short(words, repo)` is the first sentence, without the asking ("please", "can you") and
without the repo it names when that is the card's repo ("in notes-api"), cut at a word to
`WORDS` words and `CHARS` characters, its first letter capitalised. Nothing is guessed beyond
that: it reads no model and invents no word. `from_words` is the pair a create files: the
short title, and the words with whatever more the user wrote as the brief. `cut` is the same
cut at a length alone, which the merge subject uses (`merging.merge_message`), so a card
filed any other way never puts a paragraph on main either.
"""

from __future__ import annotations

import re

WORDS = 9
CHARS = 60
# the asking a sentence to a colleague opens with, which a title does not need
ASKING = re.compile(r"^(?:please|can you|could you|would you|will you|i want you to|i'd like you to)\b[,:]?\s+", re.I)
TRAILING = " ,;:-"


def cut(text: str, chars: int, words: int | None = None) -> str:
    """`text` cut at a word to at most `words` words and `chars` characters."""
    parts = " ".join(str(text or "").split()).split(" ")
    if words is not None:
        parts = parts[:words]
    while len(parts) > 1 and len(" ".join(parts)) > chars:
        parts.pop()
    return " ".join(parts).rstrip(TRAILING)


def naming(repo: str | None):
    """The opening that names `repo`: "in notes-api", "in the notes-api repo:"."""
    if not repo:
        return None
    return re.compile(rf"^in\s+(?:the\s+)?{re.escape(repo)}(?:\s+repo)?\b[,:]?\s+", re.I)


def short(words: str, repo: str | None = None) -> str:
    text = " ".join(str(words or "").split())
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s+", text)[0].rstrip(".!? ")
    openings = [pattern for pattern in (ASKING, naming(repo)) if pattern is not None]
    moved = True
    while moved:
        moved = False
        for pattern in openings:
            found = pattern.match(first)
            if found and found.end() < len(first):
                first, moved = first[found.end():], True
    title = cut(first, CHARS, WORDS)
    return title[:1].upper() + title[1:]


def from_words(words: str, more: str = "", repo: str | None = None) -> tuple[str, str]:
    """`(title, brief)` for a card filed from the user's words: the short title, and the
    words as the brief's first paragraph unless the title is all of them."""
    said = str(words or "").strip()
    title, more = short(said, repo), str(more or "").strip()
    if title == said:
        return title, more
    return title, "\n\n".join(part for part in (said, more) if part)
