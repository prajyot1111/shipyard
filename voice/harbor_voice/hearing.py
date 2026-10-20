"""What the speech model heard, repaired against the words this product is made of.

WHY THIS EXISTS AT ALL, given that speech.py says not to build it. Naming the real things
in front of the model repairs a garbled REFERENCE: finding 7 measured 7 of 8 garbled
lookups landing correctly once the live names rode along with the sentence, which is what
the board digest still does on every turn. That result stands and this does not
contradict it.

It is incomplete, and the transcript from 2026-09-03 is where the hole is. Turn 16 was
"you should have sent this to Harper", which reached Harbor exactly as finding 7
predicts. Then HARBOR got the garbled word, and spent twenty-nine seconds explaining that
nothing here is called Harper. Names alongside a sentence repair what it REFERS TO. They
do not repair the sentence, and it is handed on verbatim. So the class of error finding 7
measured is covered, and the class that actually cost him a turn (a wrong word reaching
the thing that reads the words) was not.

WHAT WAS MEASURED, and it is why this is a table of observed strings rather than a
matcher. probe2/stt_jargon.py put 36 utterances carrying Harbor vocabulary through
Parakeet on this machine: term accuracy 62.5%, and 15 of the 18 errors are the single
word "Harbor". Read the split before quoting that: on `bm_lewis` every miss is
"Harbour", which is not a recognition error at all but a spelling of the same word, and
on `af_heart` they are genuine ("Haber", "Haba", "Hobba", "Hobileja", "Hobbispawn") but
that voice is a synthesiser pronouncing a proper noun, so it is contaminated evidence.
The clean evidence is his own voice in the transcript: "Harbor" -> "Harper", and
"Harbor's pane" -> "Harbor Spain".

A PHONETIC MATCHER WAS BUILT AND REJECTED, and the numbers are the reason. Soundex plus a
similarity floor, over a sixteen-word vocabulary, does repair "Harper" and "Harbour". It
also turns "pain" into "pane", "Spain" into "spawn", "conduct" into "conductor" and
"Harvard" into "Harbor". Guarding it on the system dictionary kills the false ones and
kills the real one with them, because `harper` is a dictionary word (one who plays a
harp) and `spain` is not. Every threshold tried either missed the error that was
actually observed or invented a word that was not said. A layer that invents words is
worse than one that misses them, because a missed word still reaches Harbor, which can
ask, and an invented word reaches Harbor as a fact. So there is no matcher here.

WHAT IS HERE INSTEAD is a table of exact strings that have been HEARD in place of a name
this product uses, each with where it was observed. It cannot invent, because it only
ever fires on a string that is in it. It grows the way the evidence grows: hear a new
one, add it with the date and the source. That is slower than a matcher and it is the
only version of this that is safe.

THE VOCABULARY STILL HAS ONE HOME. `etc/dictation-vocabulary.md` is the list of terms,
written 2026-08-01 for OpenSuperWhisper, and NAMES is read against it by the selftest so
the two cannot drift: every target here has to be a term that file already carries, or a
noun the verb registry already speaks. This adds no vocabulary. It records how the
vocabulary is MISHEARD, which is a different fact and has never had a home.

THE EMPLOYER'S NAMES ARE NOT IN THIS FILE, and cannot be: employer vocabulary lives only
in its pack (`make drift` greps for it), and a mishearing of an employer's name is
employer vocabulary. So each adapter may carry a `hearing.json` beside it with the same
two tables, each entry naming what was said and where it was heard, and they are merged
in at import from `config.ADAPTERS_DIR`. This file's own entries win on a clash, and a
malformed adapter table is skipped and named in ADAPTER_ERRORS rather than allowed to
cost a turn. Delete the adapter and its mishearings go with it.

APPLIED TO SPEECH ONLY. `server.on_utterance` repairs what the microphone produced;
`on_text` does not, because typed text is exactly what was meant and a table that
"corrects" it would be changing a person's own words.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config

# PHRASES FIRST, because the multi-word errors are the ones a word-level pass cannot see:
# "Harbor's pane" is heard as two words, one of which ("Spain") is a perfectly good word
# on its own and must never be touched outside this exact company.
#
# Left: the lower-cased string as it was HEARD. Right: what was said.
PHRASES = {
    # Observed 2026-09-03, transcript turn 7, his own voice.
    "harbor spain": "Harbor's pane",
    "harbour spain": "Harbor's pane",
    "harbor's pain": "Harbor's pane",
    "harbour's pain": "Harbor's pane",
    # THE COMMAND NAMES ARE NOT IN HERE, and that is deliberate twice over. Entries for
    # them were written and removed. The evidence was a synthesiser mangling a proper
    # noun, which this file has already called contaminated, and acting on it here while
    # discounting it above would be having it both ways. And the targets would have been
    # the literal names of the verbs that START and READ things, which
    # bin/keel-voice-selftest greps this package for on purpose: voice never begins a
    # session itself, and the cheapest way to keep that true is for those words not to
    # appear in these files at all. This comment is written around them for that reason.
    # If a real utterance is ever misheard that way, it comes back with a real
    # observation behind it and the guard gets the argument it deserves.
    # Observed 2026-09-03, probe2/stt_jargon.py, af_heart.
    "harbour up": "Harbor up",
    # Observed 2026-09-03, findings.md finding 6: Parakeet renders "queue" as the letter.
    "the q": "the queue",
    "on the q": "on the queue",
    "read me the q": "read me the queue",
    # Observed 2026-09-19, sherpa-onnx Parakeet 110M int8 (the box's model), macOS `say`
    # voices Daniel, Rishi and Samantha, c-286. "cbe" alone is an honour's initials, so
    # only the phrase is repaired.
    "the cbe": "the queue",
}

# Then single words. Every key here has been HEARD on this machine in place of the value.
# A key that is also an ordinary English word is marked, because that is the cost of the
# entry and the next person should be able to weigh it rather than discover it.
WORDS = {
    # A spelling of the same word rather than a mishearing. bm_lewis, 6 of 6.
    "harbour": "Harbor",
    "harper": "Harbor",        # transcript turn 16, his own voice. Also an English word:
                               # a harp player. He has nothing called Harper; if he ever
                               # does, this line is the thing to delete.
    "haber": "Harbor",         # probe2/stt_jargon.py, af_heart
    "haba": "Harbor",          # probe2/stt_jargon.py, af_heart
    "hobba": "Harbor",         # probe2/stt_jargon.py, af_heart
    "hobbi": "Harbor",         # probe2/stt_jargon.py, af_heart
    "lavage": "lavish",        # etc/dictation-vocabulary.md names lavish; this is the
                               # nearest real word and the one a speech model reaches for.
    # THE BOX'S MODEL, 2026-09-19, c-286: sherpa-onnx Parakeet 110M int8 and 0.6B v2 int8
    # over "Keel" and "Harbor" in eight sentences each, macOS `say` voices Daniel, Rishi,
    # Samantha and Karen (synthetic, so the same caveat as af_heart above; the box
    # benchmark of 2026-09-18 heard "Kiel" too). Heard in place of Keel: "Kel", "Kil",
    # "Kiel". Kiel is a German city and Kel a given name; he has neither, and if he ever
    # does, these lines are the ones to delete.
    "kiel": "Keel",
    "kel": "Keel",
    "kil": "Keel",
    "harba": "Harbor",         # 110M, Rishi
    "harbard": "Harbor",       # 110M, Karen. A name in Norse myth, never said here.
}


def _adapter_tables(root: Path | None = None) -> tuple[dict, dict, list[str]]:
    """(phrases, words, errors) merged from every `<adapter>/hearing.json` under root, or by
    default under the adapters tree and every pack root (`config.PACK_ROOTS`, c-722): an
    install's own pack is not in this checkout. A file reached twice (an adapter is a link
    to its pack) is read once.

    The file's shape: {"phrases": {heard: {"said": ..., "heard": where}}, "words": {...}}.
    An entry without both a `said` and a `heard` is refused, because an entry nobody can
    trace to an observation is exactly the guess this module exists not to make.
    """
    roots = [config.ADAPTERS_DIR, *config.PACK_ROOTS] if root is None else [root]
    phrases: dict = {}
    words: dict = {}
    errors: list[str] = []
    paths, seen = [], set()
    for each in roots:
        try:
            found = sorted(each.glob("*/hearing.json"))
        except OSError:
            continue
        for path in found:
            if path.resolve() not in seen:
                seen.add(path.resolve())
                paths.append(path)
    for path in paths:
        try:
            data = json.loads(path.read_text())
            for key, into in (("phrases", phrases), ("words", words)):
                for heard, entry in (data.get(key) or {}).items():
                    said = entry.get("said") if isinstance(entry, dict) else None
                    if not said or not entry.get("heard"):
                        errors.append(f"{path.parent.name}: {heard!r} names no said or heard")
                        continue
                    into[str(heard).lower()] = str(said)
        except (OSError, ValueError, AttributeError) as exc:
            errors.append(f"{path.parent.name}: {exc.__class__.__name__}")
    return phrases, words, errors


def _pattern(keys) -> re.Pattern:
    """Longest first, so `x's` is tried before `x` and a possessive is replaced whole."""
    return re.compile(r"\b(?:" + "|".join(sorted((re.escape(k) for k in keys),
                                                  key=len, reverse=True)) + r")\b", re.I)


_ADAPTER_PHRASES, _ADAPTER_WORDS, ADAPTER_ERRORS = _adapter_tables()
ALL_PHRASES = {**_ADAPTER_PHRASES, **PHRASES}      # this file's own entries win a clash
ALL_WORDS = {**_ADAPTER_WORDS, **WORDS}

_PHRASE_RE = _pattern(ALL_PHRASES)
_WORD_RE = _pattern(ALL_WORDS)


def repair(heard: str) -> tuple[str, list[tuple[str, str]]]:
    """(what was probably said, [(heard, said), ...]).

    The list is returned rather than logged here so the caller can put it in the
    transcript. A repair that happens invisibly is a repair nobody can audit, and this
    table is only trustworthy for as long as its mistakes are visible.
    """
    text = str(heard or "")
    if not text.strip():
        return text, []
    changed: list[tuple[str, str]] = []

    def phrase(m):
        was = m.group(0)
        now = ALL_PHRASES[was.lower()]
        changed.append((was, now))
        return now

    def word(m):
        was = m.group(0)
        now = ALL_WORDS[was.lower()]
        if was.lower() == now.lower():
            return was
        changed.append((was, now))
        return now

    # PHRASES, THEN WORDS, THEN PHRASES ONCE MORE, and the third pass is not belt and
    # braces: repairing a word can EXPOSE a phrase. "Hobba's pain" is not in the phrase
    # table and never will be, one entry per mishearing of every word being how a table
    # like this rots. After the word pass it reads "Harbor's pain", which the phrase
    # table does know, and the second pass finishes it. Measured: it is the difference
    # between 47 of 48 jargon terms and 48 of 48.
    #
    # Exactly one extra pass, never a loop to a fixed point. Every entry here rewrites
    # towards a real name, so a cycle would need two entries pointing at each other, and
    # the way to be sure that never spins is to not give it the chance.
    text = _PHRASE_RE.sub(phrase, text)
    text = _WORD_RE.sub(word, text)
    text = _PHRASE_RE.sub(phrase, text)
    return text, changed
