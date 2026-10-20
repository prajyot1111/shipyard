"""The one instant answer: "what's waiting on me", rendered by code from the board.

WHAT IS LEFT OF THE LOOKUP TIER, AND WHY IT IS THIS ONE. The router, the argument
resolver, the thirteen verbs and the 436 scored utterances were deleted on 2026-09-18
(decision D4, `<install>/history/docs/voice-two-modes.md` section 4): neither of the two modes needs them,
converse sends every turn to the model and capture asks nothing. The one thing worth
keeping is the question he actually asks out loud, twice in the transcript, and whose
answer is three bytes of JSON: what is waiting on him.

NO CLASSIFIER, NO MODEL, NO ROUTER. `WAITING` below is a table of whole utterances that
have been said, or would plainly be said, matched after `hearing.repair` against the
whole sentence, case-insensitively, with trailing punctuation ignored. It cannot misfire
on "what's waiting at the supermarket", because that string is not in the table, which is
the difference between this and the thing it replaces: the router answered 6 of every 90
ordinary sentences out of the ledger as though they were about the board.

THE RULE THE RENDERER STILL ENFORCES, and it is the one the probes caught being broken:

    Code may state what the record states, and it may COUNT.
    It may never derive a JUDGEMENT.

"2 pending: 1 approval and 1 notice, the top one is X" is allowed. "Nothing needs a
decision" is not, and that is not a hypothetical: an early renderer said exactly that
against live state while two entries needed a decision, because every pending entry
carried kind "notice" and the code concluded from a field what the field does not mean.
Code-rendering stops the MODEL inventing a fact. It does not stop the CODE inventing one.

THE VERBATIM RULE IS STRUCTURAL. Anything quoted from a waiting card is a string this
file copies. No model ever holds it, so there is no path by which one rewrites authority
text.

A RENDER THAT CANNOT ANSWER RAISES, and the turn falls to the model: see dispatcher.py.
That is the only failure direction anywhere in this package.
"""
from __future__ import annotations

import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import harbor_queue_fold as qfold                                       # noqa: E402

from . import snapshot                                                  # noqa: E402

# EVERY STRING HERE IS A WHOLE UTTERANCE, and the two marked "observed" are his own words
# out of `state/voice/transcript.jsonl`. The rest are the same question in the wordings a
# person reaches for; each one is written out rather than matched by a pattern, because a
# pattern is a classifier with fewer measurements behind it. Add a line when a real
# utterance misses, the way hearing.py grows: with the date and where it was heard.
WAITING = frozenset({
    "hey, anything waiting on me",         # observed 2026-09-17, his own voice
    "what is waiting on me right now",     # observed 2026-09-17, his own voice
    "what's waiting on me",
    "whats waiting on me",
    "what is waiting on me",
    "what's waiting on me right now",
    "anything waiting",
    "anything waiting on me",
    "what needs me",
    "what's waiting for me",
    "whats waiting for me",
    "what is waiting for me",
})

# Trailing punctuation only. A comma inside the sentence is part of what he said ("hey,
# anything waiting on me"), so it stays in the table rather than being stripped out.
_TRAILING = re.compile(r"[.!?\s]+$")


def normalise(said: str) -> str:
    """Lower-cased, whitespace collapsed, trailing punctuation dropped. Nothing else."""
    return _TRAILING.sub("", " ".join(str(said or "").split())).lower()


def is_waiting_question(said: str) -> bool:
    """Whether this WHOLE utterance is the one question code answers."""
    return normalise(said) in WAITING


# c-300's FIXED MENU OF ABOUT FIVE READS, named here because V10's `route` answer can say
# `board_read` and something has to say what that could mean. Exactly ONE of them has a
# renderer today, and that is deliberate (his call at c-314's plan gate): this card builds
# the PATH, a reply that never passes through Harbor, and the other four renderers are a
# follow-up. A `board_read` verdict for a read with nothing to render it falls to Harbor,
# which is this package's one failure direction, and is counted as such.
BOARD_READS = ("needs-you", "building", "backlog", "reviews", "card-by-id")


def board_read(said: str) -> str:
    """Which fixed read this WHOLE utterance is, or "" when it is none of them.

    The one entry with a renderer is `needs-you`, and it is the same table
    `is_waiting_question` reads, so the two can never disagree about what code answers.
    """
    return "needs-you" if is_waiting_question(said) else ""


# --------------------------------------------------------------------------- #
# The two conversation words (V2, V3), and they are tables for the same reason
# `WAITING` is one.
# --------------------------------------------------------------------------- #

# WHAT ENDS A CONVERSATION. V2 names "that's all" and this is that phrase in the
# wordings a person reaches for, matched against the WHOLE utterance exactly as
# `WAITING` is, so it can never fire inside a sentence that merely contains the words
# ("that's all I could find in the log" is not in this table and cannot be).
#
# IT IS MATCHED IN TWO PLACES AND THE TABLE LIVES IN ONE. The gateway matches it before
# a turn is dispatched, so the words that end a conversation never cost a Harbor turn;
# the page matches the transcript it is sent, so a conversation still ends correctly
# against a gateway that predates this. `config.flags_for_page` serves this set to the
# page, the way it already serves the mode and the engine list, so there is no second
# copy to drift.
END_CONVERSATION = frozenset({
    "that's all",
    "thats all",
    "that is all",
    "that's all for now",
    "thats all for now",
    "that's it",
    "thats it",
    "that's everything",
    "thats everything",
    "we're done",
    "were done",
    "we are done",
    "i'm done",
    "im done",
    "nothing else",
    "stop listening",
})

# WHAT PAUSES ONE. V3 is explicit that the TAP is primary and the phrase is the
# secondary way in, because the moment he turns to someone else he is already talking.
# So this table is deliberately short: every line here is a phrase that is almost never
# the beginning of something he wanted Harbor to hear.
PAUSE_CONVERSATION = frozenset({
    "hold on",
    "hold on a second",
    "hold on a minute",
    "hang on",
    "hang on a second",
    "one second",
    "one moment",
    "give me a second",
    "give me a minute",
    "wait a second",
})


def is_end_of_conversation(said: str) -> bool:
    """Whether this WHOLE utterance is him closing the conversation."""
    return normalise(said) in END_CONVERSATION


def is_pause(said: str) -> bool:
    """Whether this WHOLE utterance is him asking for a pause."""
    return normalise(said) in PAUSE_CONVERSATION


# --------------------------------------------------------------------------- #
# Connecting to one card's house (V4), and the same rule again: a table of whole
# phrases plus a card id, NEVER the model.
# --------------------------------------------------------------------------- #

# THE PHRASE IS EXACT AND THE ID IS PARSED. An utterance connects only when it is one of
# these openings followed by something that reads as a card id, so "connect the speaker to
# the amp" cannot reach a house: "connect the speaker to" is not an opening, and "the amp"
# is not an id. V4 says "matched by the exact-phrase table plus a card id, never by the
# model", and this is the whole of that mechanism.
#
# THE ENTERING WORDS ARE HIS OWN (V13, 2026-09-21): "hey can you enter this house, I need
# to check some things". Once the thing that moves is HARBOR rather than the microphone,
# "enter" and "go into" are what a person reaches for, and they cost nothing to add
# because the second half of the rule is unchanged: whatever follows the opening must read
# as a card id or nothing happens. "enter 272 into the form" connects to nothing, because
# "into the form" is not a number and `card_id_in` answers "" the moment it meets a word
# that is not part of one.
CONNECT_OPENINGS = (
    "connect me to",
    "connect me with",
    "connect to",
    "put me through to",
    "put me on to",
    "talk to",
    "let me talk to",
    "i want to talk to",
    "speak to",
    "let me speak to",
    "enter",
    "go into",
    "step into",
    "take me into",
)
# WHAT ENDS IT, in the wordings a person reaches for, matched against the WHOLE utterance
# exactly as `WAITING` and `END_CONVERSATION` are. "Back to Harbor" is V4's own phrase; the
# leaving words are V13's, and they are the other half of his sentence ("similarly it
# exits"). They are whole utterances, so "leave" is the whole of what he said and cannot
# fire inside "leave that for tomorrow".
DISCONNECT = frozenset({
    "back to harbor",
    "back to harbour",
    "go back to harbor",
    "go back to harbour",
    "back to the board",
    "disconnect",
    "disconnect me",
    "hang up",
    "never mind the card",
    "leave",
    "leave the house",
    "exit",
    "exit the house",
    "come back",
    "come back out",
    "step out",
    "step outside",
})

# The filler between the opening and the id: "connect me to CARD 272", "talk to THE HOUSE
# on c-272". Dropped before the number is read, and nothing else is.
_ID_FILLER = ("card", "the card", "the house on", "the house", "house", "the", "agent",
              "the agent", "session", "c card")
# Parakeet writes a card id several ways: "c-272", "c 272", "c272", "see 272", and the
# digits one at a time when he says them that way. `_DIGIT_WORDS` covers the spoken forms
# of a number up to three digits, which is every card id the board has ever had.
_DIGIT_WORDS = {"zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4,
                "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS_WORDS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
               "seventy": 70, "eighty": 80, "ninety": 90}
_LEAD = re.compile(r"^(?:c|see|sea|si)[\s-]*", re.I)
_CARD_ID = re.compile(r"^c-?(\d{1,4})$", re.I)


def _strip_filler(text: str) -> str:
    words = text.split()
    while words:
        for filler in sorted(_ID_FILLER, key=len, reverse=True):
            parts = filler.split()
            if [w.strip(",") for w in words[:len(parts)]] == parts:
                words = words[len(parts):]
                break
        else:
            break
    return " ".join(words)


def _number_from_words(text: str) -> str:
    """The digits in a spoken number, or "".

    A card id is SAID in three shapes and this reads all of them the same way: as a list
    of chunks written out one after the other. "two seven two", "two seventy two" and
    "three fifteen" are 272, 272 and 315, because each chunk keeps its own digits
    ("seventy two" is one chunk, 72, and so is "fifteen"). "Hundred" is the exception and
    the only place arithmetic happens: "two hundred and seventy two" is 272 as a number.
    Anything that is not part of a number ends the read and answers "", which is what
    makes "talk to Sarah about it" unable to reach a house.
    """
    words = [word.strip(",.").lower() for word in text.replace("-", " ").split()]
    words = [word for word in words if word and word != "and"]
    if not words:
        return ""
    chunks: list[int] = []
    hundreds = False
    index = 0
    while index < len(words):
        word = words[index]
        if word == "hundred":
            if not chunks:
                return ""
            chunks[-1] *= 100
            hundreds = True
        elif word.isdigit():
            chunks.append(int(word))
        elif word in _TENS_WORDS:
            value = _TENS_WORDS[word]
            if index + 1 < len(words) and words[index + 1] in _DIGIT_WORDS \
                    and _DIGIT_WORDS[words[index + 1]] < 10:
                value += _DIGIT_WORDS[words[index + 1]]
                index += 1
            chunks.append(value)
        elif word in _DIGIT_WORDS:
            chunks.append(_DIGIT_WORDS[word])
        else:
            return ""
        index += 1
    if not chunks:
        return ""
    number = sum(chunks) if hundreds else int("".join(str(chunk) for chunk in chunks))
    return str(number) if 0 < number < 10000 else ""


def card_id_in(text: str) -> str:
    """The card id in this fragment, as the board spells it (`c-272`), or "".

    Three digits with a leading zero is how the board writes its own ids (`c-001`), so a
    number is padded to three. Nothing here asks the board whether the card exists: the
    gateway does that before it pins, because a card id that parses and does not exist is
    a thing to say out loud, not a silent miss.
    """
    text = _strip_filler(" ".join(str(text or "").split()).lower().strip(" .,?!"))
    if not text:
        return ""
    direct = _CARD_ID.match(text.replace(" ", ""))
    if direct:
        return f"c-{int(direct.group(1)):03d}"
    number = _number_from_words(_LEAD.sub("", text, count=1))
    return f"c-{int(number):03d}" if number else ""


# BOSUN IS THE ONE TARGET THAT IS NOT A CARD (c-523, BO-5): "put me through to Bosun". Its
# name the way speech recognition writes it, matched against the WHOLE rest of the
# utterance after an opening, exactly as a card id is: "talk to Bosun about the drain" is a
# question for Harbor, not a connect, because "about the drain" is not part of the name.
BOSUN = "bosun"
BOSUN_NAMES = frozenset({"bosun", "the bosun", "bo'sun", "the bo'sun", "boson", "the boson",
                         "boatswain", "the boatswain"})


def target_in(text: str) -> str:
    """`bosun` when this fragment is Bosun's name, else the card id in it, or ""."""
    name = " ".join(str(text or "").split()).lower().strip(" .,?!")
    if name in BOSUN_NAMES or _strip_filler(name) in BOSUN_NAMES:
        return BOSUN
    return card_id_in(text)


def connect_target(said: str) -> str:
    """The card (or `bosun`) this utterance asks to be connected to, or "".

    The opening must be the START of the whole utterance and the rest must read as an id,
    or as Bosun's name.
    """
    text = normalise(said)
    for opening in sorted(CONNECT_OPENINGS, key=len, reverse=True):
        if text.startswith(opening + " "):
            return target_in(text[len(opening):])
    return ""


def is_disconnect(said: str) -> bool:
    """Whether this WHOLE utterance is him going back to Harbor."""
    return normalise(said) in DISCONNECT


# --------------------------------------------------------------------------- #
# Leaving in his own words (2026-09-21), and it is a SECOND reading beside the
# table above rather than a looser version of it.
# --------------------------------------------------------------------------- #

# WHAT HE ACTUALLY SAID. Inside c-302, in his second session of 2026-09-21: "Okay, you can
# exit the pouse now", and then "You can go back". Neither is in `DISCONNECT`, because
# `is_disconnect` matches the WHOLE utterance against a fixed set, so both went to the
# house as questions; it answered "I can't end my own session, tap Stop on the deck",
# which was true, and he had to tap the header to get out.
#
# A PERSON DOES NOT SAY A TABLE ENTRY. He says a leave phrase wrapped in the words people
# wrap everything in ("okay", "you can", "now"), and speech recognition mangles the noun on
# the end: "pouse" is his own transcript. So the table stays exactly as it is, and this
# reads the wrappers off and asks the table's question of what is left.
#
# EVERY RULE HERE IS ABOUT A QUESTION BEING UNABLE TO TRIP IT, because the two mistakes are
# not the same size. A leave that is missed costs him one more sentence and a tap; a
# question read as a leave ends a conversation he was in the middle of, and the house's
# work goes back to sleep. A sentence is a leave only when all four hold:
#
#   1. TEN WORDS AT MOST. "Can you exit the house once the tests are green and you have
#      pushed it" is a sentence about the work.
#   2. NO QUESTION OPENER. "why did you exit the loop", "how do I go back to the previous
#      version", "tell me how to get out of this branch": a question ABOUT a leave word is
#      never a leave.
#   3. A LEAVE PHRASE AT THE FRONT of what is left once the lead-ins and a trailing
#      "now"/"please" are off it. His sentence becomes "exit the pouse".
#   4. AND NOTHING AFTER IT BUT AN OBJECT: the house (however it was heard), the card, it,
#      here, or "to" one of the places this conversation can go back to. That last rule is
#      the whole difference between "go back to harbor" and "go back to the first
#      decision", and between "leave" and "leave that file alone".
LEAVE_MAX_WORDS = 10
# The words that wrap a request, taken off the front one at a time. "harbor" is here
# because he addresses it by name ("harbor, get out of here").
LEAVE_LEAD_INS = ("okay", "ok", "alright", "all right", "yeah", "yep", "so", "please",
                  "you can", "can you", "could you", "now", "then", "harbor", "harbour")
# And off the back, for the same reason.
LEAVE_TRAILERS = ("now", "please")
# THE PHRASES THEMSELVES, and they are the table's own words plus the ones a person
# reaches for when the thing that moves is Harbor. Longest first at the point of use, so
# "back to harbor" is read before "back to".
LEAVE_PHRASES = ("exit", "leave", "get out", "step out", "come back", "go back",
                 "back to harbor", "back to harbour", "back to you", "hang up",
                 "disconnect", "that's all", "thats all", "done here", "we're done",
                 "were done")
# HOW THE NOUN COMES OUT OF SPEECH RECOGNITION. "pouse" is his own transcript, 2026-09-21;
# the others are what the same word turns into when it is said quickly at the end of a
# sentence. Matched loosely BECAUSE IT IS ONLY EVER READ AFTER A LEAVE PHRASE: a wrong
# reading of "mouse" can do nothing unless he also said "exit" or "leave" in front of it.
HOUSE_HEARD = frozenset({"house", "pouse", "mouse", "how's", "hows", "houses"})
LEAVE_OBJECTS = frozenset({"it", "here", "out", "card", "conversation"}) | HOUSE_HEARD
# WHERE A LEAVE MAY GO BACK TO. Anything else after "to" is a question about the work.
LEAVE_BACK_TO = frozenset({"harbor", "harbour", "you", "the board", "the deck"})
LEAVE_QUESTIONS = ("why", "how", "what", "when", "where", "which", "can you explain",
                   "tell me")


def _without_lead_ins(text: str) -> str:
    """His sentence with the words people wrap everything in taken off the front."""
    out = text
    moved = True
    while moved and out:
        moved = False
        for lead in sorted(LEAVE_LEAD_INS, key=len, reverse=True):
            if out == lead:
                return ""
            if out.startswith(lead + " ") or out.startswith(lead + ","):
                out = out[len(lead):].lstrip(" ,")
                moved = True
                break
    return out


def _without_trailers(text: str) -> str:
    """The same off the back: "exit the house now" is "exit the house"."""
    out = text
    moved = True
    while moved and out:
        moved = False
        for tail in LEAVE_TRAILERS:
            if out == tail:
                return ""
            if out.endswith(" " + tail):
                out = out[:-len(tail) - 1].rstrip(" ,")
                moved = True
                break
    return out


def _leave_object(rest: str) -> bool:
    """What may follow a leave phrase: nothing, the thing he is leaving, or where to."""
    rest = rest.strip(" ,")
    if not rest:
        return True
    if rest.startswith("to "):
        return rest[3:].strip() in LEAVE_BACK_TO
    words = rest.split()
    if words and words[0] == "of":
        words = words[1:]
    if words and words[0] in ("the", "this", "that"):
        words = words[1:]
    return len(words) == 1 and words[0] in LEAVE_OBJECTS


def leave_intent(said: str) -> bool:
    """Whether this is him asking to come out of the house, in whatever words.

    THE TABLE IS ASKED FIRST AND IT IS UNCHANGED, so this can only ever add: every whole
    utterance that ended a conversation before still ends one, and the lenient reading
    below is what catches the sentence he actually said.
    """
    if is_disconnect(said):
        return True
    text = normalise(said)
    if not text or len(text.split()) > LEAVE_MAX_WORDS:
        return False
    if any(text == opener or text.startswith(opener + " ")
           for opener in LEAVE_QUESTIONS):
        return False
    rest = _without_trailers(_without_lead_ins(text))
    for phrase in sorted(LEAVE_PHRASES, key=len, reverse=True):
        if rest == phrase:
            return True
        if rest.startswith(phrase + " "):
            return _leave_object(rest[len(phrase):])
    return False


# --------------------------------------------------------------------------- #
# Connecting by DESCRIPTION (c-419): the model picks the house, the gateway pins.
# --------------------------------------------------------------------------- #

# WHY THERE IS A SECOND WAY IN AT ALL, in his own words: "oftentimes I won't be knowing
# the house number, so I will be relying on the model to tell me". The phrase table above
# is the floor and it is unchanged: an opening plus an id still pins before any judge and
# before anything is dispatched. What is added is the sentence the table cannot parse
# ("connect me to the house doing the voice thing"), which goes to Harbor as an ordinary
# question and comes back with ONE card named in it.
#
# THE MODEL NAMES A CARD. IT NEVER PINS. Only the gateway runs `keel converse`, so what
# Harbor can do is end its answer with a directive, and what this file does is read it.
# Every guard, every refusal and every spoken line of the handoff belong to the connect
# path that already exists (`server.Gateway.connect_to`), which this reaches unchanged.
#
# THE KEY IS THE WHOLE OF "IMPOSSIBLE TO PRODUCE BY ACCIDENT". A fixed sentinel on its own
# is producible by an answer that QUOTES it, and "how does the connect work" is a question
# he can ask out loud. So the gateway mints six random hex characters for each Harbor turn,
# puts them in that turn's framing, and pins only for a directive carrying THAT turn's key:
# it is not in his speech, not in the digest, not in an earlier answer, and a model cannot
# guess it. A stale or mistyped key is a MISS, which costs a sentence he hears and never a
# pin to the wrong house.
CONNECT_MARK = "keel-connect"
# 3 bytes, said as 6 hex characters: short enough that a model copies it without trouble,
# and there is nothing to attack here. The threat this closes is accident, not forgery.
CONNECT_KEY_BYTES = 3
# WHAT MAY PIN: an id, this turn's key, and NOTHING AFTER IT.
#
# "ALONE ON THE LAST LINE" IS WHAT HARBOR IS TOLD, AND "AT THE VERY END" IS WHAT IS
# CHECKED, because the answer never reaches this file with its newlines. Every line into
# the say inbox is flattened (`harbormsg.SayInbox.write` does `" ".join(text.split())`,
# and that is the channel's rule, shared with `progress` and `opening`), so a rule about
# lines would be a rule about something the gateway cannot see. The instruction stays the
# line, because a directive written on its own line is a directive at the end once the
# inbox has flattened it; the check is the property that survives.
#
# NOT EVEN A FULL STOP AFTER IT. A model explaining the mechanism ("you would end with
# <<keel-connect c-317 abc123>> on the last line") writes words after the token and pins
# nothing, which is the case this strictness is bought for. A miss costs one sentence he
# hears and can answer; a wrong pin costs a house he never asked for.
_DIRECTIVE = re.compile(r"<<\s*keel-connect\s+(c-?\d{1,4}|bosun)\s+([0-9a-f]{4,12})\s*>>\s*$",
                        re.I)
# WHAT IS NEVER SPOKEN: anything of that shape, wherever it sits. Read aloud, the token is
# gibberish however it got into the answer, so stripping is by SHAPE and pinning is by
# shape and place and key. That split is what lets a sentence merely CONTAINING the shape
# be an ordinary answer rather than a connect.
_DIRECTIVE_SHAPE = re.compile(r"<<[^<>\n]{0,80}?keel-connect[^<>\n]{0,80}?>>", re.I)


def connect_key() -> str:
    """A fresh key for one Harbor turn. Minted per turn, never reused, never stored."""
    return secrets.token_hex(CONNECT_KEY_BYTES)


def connect_directive(answer: str, key: str = "") -> tuple[str, str]:
    """(what is spoken, the card to connect to or "").

    THE ANSWER IS RETURNED UNTOUCHED unless the shape is actually in it, so an ordinary
    turn keeps its own whitespace and nothing about the common case changes.

    THE DIRECTIVE MUST END THE ANSWER. A directive quoted inside a sentence is text: it
    is stripped, because it would be gibberish out loud, and it pins nothing. An empty
    `key` (a house's answer, a turn that never carried one) can match nothing, which is
    how a house is kept from moving the pin.
    """
    text = str(answer or "")
    if not _DIRECTIVE_SHAPE.search(text):
        return text, ""
    card = ""
    match = _DIRECTIVE.search(text)
    if match and key and match.group(2).lower() == str(key).strip().lower():
        card = target_in(match.group(1))
    return flat(_DIRECTIVE_SHAPE.sub(" ", text)), card


# AN ANSWER TO ONE OF BOSUN'S ASKS, BY VOICE (c-523, BO-5), and it is the connect
# directive's twin in every rule: this turn's key, the very end of the answer, stripped by
# shape wherever it sits, and acted on only when the answer was spoken. Harbor reads him the
# options, says his pick back and writes it only on his yes; the letter is A to D and
# nothing else. An answer in his own words (a redirect) is not taken by voice: the words
# that matter were said in an earlier turn, and a redirect recorded with only his "yes"
# would reach Bosun carrying no instruction. The gateway does not record it: the voice
# PAGE does, because the page is him on the deck and the gateway holds no token
# (`actions.voice_answer`).
_ANSWER = re.compile(r"<<\s*keel-answer\s+(a-\d{1,5})\s+([a-d])\s+([0-9a-f]{4,12})\s*>>\s*$",
                     re.I)
_ANSWER_SHAPE = re.compile(r"<<[^<>\n]{0,80}?keel-answer[^<>\n]{0,80}?>>", re.I)


def answer_directive(answer: str, key: str = "") -> tuple[str, tuple[str, str] | None]:
    """(what is spoken, (the ask, its letter) or None)."""
    text = str(answer or "")
    if not _ANSWER_SHAPE.search(text):
        return text, None
    picked = None
    match = _ANSWER.search(text)
    if match and key and match.group(3).lower() == str(key).strip().lower():
        picked = (match.group(1).lower(), match.group(2).upper())
    return flat(_ANSWER_SHAPE.sub(" ", text)), picked


# --------------------------------------------------------------------------- #
# What the house says when it takes the microphone (V8, card c-316), and it is a
# COPY AND A CUT, which is the only kind of rendering this file does.
# --------------------------------------------------------------------------- #

# HOW A CARD ID IS SAID OUT LOUD, and it was measured rather than assumed. Chirp 3 HD reads
# "c-272" as about 2.72 s inside a carrier sentence, which is where "c dash two seven two"
# (2.72 s) and "c minus two seven two" (2.80 s) land, and nowhere near "c two seventy two"
# (2.36 s). So the hyphen is spoken, one way or the other, and neither reading is a thing a
# person says. "card 272" is what HE says (it is in `_ID_FILLER` above because the parser
# had to learn it), it is unambiguous by ear, and it costs about half a second more.
# Measured on 2026-09-20 against his own key, by synthesising each and comparing lengths.
def say_card(card: str) -> str:
    """A card id as it should be SPOKEN: `c-272` becomes `card 272`.

    The page and the deck keep the written form. This is the one place the spoken form is
    made, so a second way of saying it cannot appear.
    """
    text = flat(card)
    if text.lower() == BOSUN:
        return "Bosun"
    match = re.match(r"^c-0*(\d+)$", text, re.I)
    return f"card {match.group(1)}" if match else text


# HOW MUCH OF A TITLE IS SAID. A card id alone is hard to recognise by ear, so line 2 reads
# the card's own title after it, and the whole title is too long to be part of a greeting:
# "Voice slice 6: the heard handoff and the house voice (V8)" is a sentence, and what is
# wanted here is a label. Cut at the first delimiter (a title's own subject is almost always
# what comes before the colon), then capped, then trimmed of a word left dangling.
#
# IN CODE, NEVER BY A MODEL, which is this file's whole rule: the title is a string copied
# and cut here, so there is no path by which a model rewrites what a card is called.
SHORT_TITLE_WORDS = 6
_TITLE_CUT = re.compile(r"[:(\[;]|,|\s-\s")
# Words that leave a sentence hanging when the cut lands after them.
_DANGLING = frozenset({"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with",
                       "that", "which", "is", "are", "at", "by", "from", "as", "its"})


def short_title(title: str) -> str:
    """A card's title in a few words, or "" when there is nothing to say."""
    text = flat(title)
    cut = _TITLE_CUT.search(text)
    if cut and cut.start() >= 3:
        text = text[:cut.start()]
    words = text.split()[:SHORT_TITLE_WORDS]
    while words and words[-1].strip(".,;:").lower() in _DANGLING:
        words.pop()
    return " ".join(words).strip(" .,;:-")


# WHAT HARBOR SAYS AS IT GOES IN AND AS IT COMES OUT (V13, 2026-09-21), and the two are a
# pair on purpose. V8 had four lines in two voices: the house greeted him, the house handed
# him back, and Harbor said it was back. There is one voice now, so there is one thing
# happening and two lines say it: Harbor is in the house, and Harbor has left it.
#
# THEY NAME THE CARD because he asked for that card, which the egress split (decision V17)
# allows as a direct answer; the unprompted line (`corpus.LEFT_HOUSE`, said when the hold
# runs out while he is quiet) names nothing.
#
# "BACK WITH YOU" RATHER THAN "HARBOR HERE, I'M BACK". The old line announced a speaker
# arriving, which is exactly the thing that is no longer true: nobody arrives, because
# nobody left. What changed is where it is, and that is what the sentence says.
ENTERING = "Entering {card}, {title}."
ENTERING_BARE = "Entering {card}."
LEAVING = "Leaving {card}. Back with you."


def entering(card: str, title: str = "") -> str:
    """What is said on the way into a house.

    A card with no title, or a title that cuts down to nothing, gets the short form rather
    than a sentence with a hole in it.
    """
    short = short_title(title)
    shape = ENTERING if short else ENTERING_BARE
    return shape.format(card=say_card(card), title=short)


def leaving(card: str) -> str:
    """What is said on the way out of one, naming the card he asked to leave."""
    return LEAVING.format(card=say_card(card))


# A REFUSAL IS SAID AS WHAT IT REFUSES (V13). `keel converse --connect` owns every reason a
# switch cannot happen and answers in its own sentence, which is right; what those
# sentences never said is WHICH ACT was refused, so "c-419 is building right now" arrived
# after "Connecting you now" and left him working out whether he was in the house or not.
# He must never be unsure whether the switch happened, so the gateway frames the reason
# with the thing it could not do.
CANNOT_ENTER = "I cannot enter {card}: {why}"
# EVERY CARD ID IN THE REASON IS SAID THE WAY HE SAYS IT, for the same measured reason
# `say_card` exists: read aloud, `c-419` is "c dash four one nine". The verb's sentences
# are written to be read with the eyes as well, so the spelling is fixed here, at the one
# place they become speech, rather than in the verb.
_SPOKEN_ID = re.compile(r"\bc-0*(\d{1,4})\b", re.I)


def cannot_enter(card: str, why: str) -> str:
    """A refusal, said as the thing it refused: the switch did not happen.

    THE REASON USUALLY OPENS WITH THE CARD'S OWN ID, and said straight after "I cannot
    enter card 419" that would name it twice in one breath, so a leading id becomes "it"
    and nothing else about the reason is touched. Its capitalisation is left exactly as the
    verb wrote it, because a capital letter mid-sentence is inaudible and rewriting words
    the verb chose is how a copy starts disagreeing with the thing it copies.
    """
    reason = flat(why)
    if reason.lower().startswith(str(card or "").lower()) and card:
        reason = "it" + reason[len(card):]
    return CANNOT_ENTER.format(card=say_card(card),
                               why=_SPOKEN_ID.sub(lambda m: f"card {int(m.group(1))}",
                                                  reason))


# --------------------------------------------------------------------------- #
# Small renderers. Every one of these is a count or a copy.
# --------------------------------------------------------------------------- #

def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


def flat(text) -> str:
    """One line of whitespace-collapsed text. Speech has no newlines."""
    return " ".join(str(text or "").split())


# WHAT THE CUTTER TAKES OFF A SENTENCE BEFORE IT IS SPOKEN, restated here rather than
# imported (V13). `keel/sentences.clean` is Keel's, on Python 3.14; this package runs in
# `.venv-voice` on 3.12 and imports nothing from `keel/`, which is what lets the speech
# stack pin an older interpreter. The claim being made is about what a STREAMED part looks
# like beside the FINAL answer, and the two are cleaned by different code today anyway:
# the cutter strips markdown off every part (`sentences.clean`), while the final answer
# keeps it (`harness.turn_answer` only collapses whitespace, because the card's record of
# the exchange is read with the eyes). So the comparison has to do the stripping itself,
# and a copy that drifts shows up as the comparison failing rather than as silence.
_MD_FENCE = re.compile(r"^[ \t]*```[^\n]*$", re.M)
# A WHOLE FENCED BLOCK, and in the answer's own shape (lane H, H5). The final answer reaches
# the comparison collapsed to one line (`drawing.read_answer`, `harness.turn_answer`), so a
# block is "```python print(x) ```" there rather than three lines, and a line-wise match on
# the marks alone left the CODE in: the parts said the cutter's stand-in, the answer still
# said the code, the two never matched and the whole answer was spoken again, code and all.
# An unclosed block runs to the end, as the cutter's `flush` treats one.
_MD_BLOCK = re.compile(r"```(.*?)(?:```|\Z)", re.S)
# The cutter's stand-in for a block, restated for the same reason the marks above are: the
# speakable form of an answer says it where the cutter said it, once per answer, and never
# for a `board` block, which the pen reports on instead (`keel/sentences.py`, FENCE_SAID).
FENCE_SAID = "There is a code block in my answer, it is on the page."
BOARD_LANG = "board"
_MD_QUOTE = re.compile(r"^[ \t]*>[ \t]?", re.M)
_MD_BULLET = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", re.M)
_MD_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.M)
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_STARS = re.compile(r"\*+")
_MD_UNDERLINES = re.compile(r"__")
# WHAT SURVIVES INTO THE COMPARISON KEY: letters and digits, nothing else. Two spellings
# of one sentence differ by punctuation and spacing far more often than by a word, and
# every character this drops is one a person cannot hear. It is a KEY and never something
# spoken: what is said out loud is always a slice of the answer's own text.
_AUDIBLE = re.compile(r"[^a-z0-9]+")


def without_code(text) -> str:
    """The answer with each fenced block as the cutter speaks it: the first code block
    becomes `FENCE_SAID`, every later one and every `board` block goes (H5)."""
    said = []

    def stand_in(match) -> str:
        body = match.group(1).lstrip()
        if body.split(None, 1)[:1] == [BOARD_LANG] or said:
            return " "
        said.append(True)
        return f" {FENCE_SAID} "
    return _MD_BLOCK.sub(stand_in, str(text or ""))


def as_heard(text) -> str:
    """One part or one answer, as it should be HEARD: no code, no markdown, whitespace
    collapsed. The SAME speakable form on both sides of V13-G7's comparison."""
    out = without_code(text)
    out = _MD_FENCE.sub(" ", out)
    out = _MD_LINK.sub(r"\1", out)
    out = _MD_QUOTE.sub("", out)
    out = _MD_HEADING.sub("", out)
    out = _MD_BULLET.sub("", out)
    out = out.replace("`", "")
    out = _MD_UNDERLINES.sub("", out)
    out = _MD_STARS.sub("", out)
    return flat(out)


def heard_key(text) -> tuple[str, list[int]]:
    """(the comparison key, where each of its characters came from in `as_heard(text)`).

    THE MAP IS THE POINT, and it is why this is not a bare `re.sub`. Deciding that what he
    heard is a PREFIX of the answer is only half of what the caller needs; the other half
    is where in the real text the unheard remainder starts, and a key with the punctuation
    squeezed out of it cannot answer that on its own.
    """
    cleaned = as_heard(text).lower()
    key, where = [], []
    for index, char in enumerate(cleaned):
        if not _AUDIBLE.match(char):
            key.append(char)
            where.append(index)
    return "".join(key), where


def pending_queue(doc: dict) -> tuple[list, list, list]:
    """(approvals, fresh notices, folded notices), THROUGH THE SHARED FOLD.

    REPAIR. An early probe read the raw array and said 20 pending where the deck said
    12. Two sources of truth immediately, in the one place the design says there must be
    one. `harbor_queue_fold` is the module the board's own readers import, and importing
    it here is what makes the phone, the desk and the spoken answer agree about an entry.

    A row that already carries `folded` is trusted; one that does not has its section
    computed, which keeps this usable against a bare list of rows in a test.
    """
    rows = [r for r in (doc.get("queue") or []) if r.get("status", "pending") == "pending"]
    if any("folded" in r for r in rows):
        def sect(r):
            return r.get("section") or qfold.qsection(r)
        approvals = [r for r in rows if not r.get("folded") and sect(r) != "fyi"]
        fresh = [r for r in rows if not r.get("folded") and sect(r) == "fyi"]
        folded = [r for r in rows if r.get("folded")]
        return approvals, fresh, folded
    return qfold.partition(rows)


def entry_title(rec: dict) -> str:
    """What a waiting entry is CALLED, as a label.

    `what` is stored already cut at about 64 characters, so it ends mid-word often
    enough that reading it as a sentence is what made an early probe say
    "...ends a dispatch's room membership too, s". It is a label here and nothing else.
    """
    return flat(rec.get("what"))


def v_queue(doc: dict, args=None) -> str:
    """How many things wait, and what the top one is called.

    REPAIR, and it is the most important one this package carries. The probe rendered
    "Nothing needs a decision. 20 notices waiting." while one entry wanted four design
    answers and another said an approval could not be resolved. Both were `kind: notice`,
    and the code turned that field into a judgement the field does not carry.

    So this NEVER says whether anything needs him. It says how many are of each kind and
    what the first one is called, and it lets him decide what that means. The counts are
    the deck's counts, through the shared fold, and the folded ones are mentioned rather
    than dropped, because a number that disagrees with the list under it is the lie the
    fold was added to stop.
    """
    approvals, fresh, folded = pending_queue(doc)
    total = len(approvals) + len(fresh)
    if not total and not folded:
        return "The queue is empty."
    if not total:
        return f"Nothing recent on the queue. {plural(len(folded), 'older notice')}."
    bits = []
    if approvals:
        bits.append(plural(len(approvals), "approval"))
    if fresh:
        bits.append(plural(len(fresh), "notice"))
    line = f"{total} pending: " + " and ".join(bits)
    if folded:
        line += f", plus {plural(len(folded), 'older notice')} folded away"
    top = (approvals or fresh)[0]
    return line + ". The top one is: " + entry_title(top) + "."


# WHICH RECORD THE ANSWER CAME FROM, said out loud, and it is what is left of the
# turn-15 fix. What he heard that day was a sentence about the work board with nothing in
# it to say which board it was, so a question about one thing got an answer about
# another and sounded exactly like an answer. A lead-in cannot stop a wrong answer; it
# makes one obvious in the first three words, which costs a breath instead of trust.
WAITING_LEAD = "On your queue: "

# ONLY WHEN THE SENTENCE DOES NOT ALREADY NAME THE RECORD. "The queue is empty" says
# where it read; leading it anyway produces "On your queue: the queue is empty", which is
# padding, and this file is strict about padding for the same reason the narration table
# is. The counted form ("2 pending: 1 approval and 1 notice") names no record at all, and
# that is the one that needs it.
_SAYS_QUEUE = re.compile(r"\bqueue\b", re.I)


def render(doc: dict) -> str:
    """One spoken sentence about what is waiting, saying where it read it.

    It must never return "I don't know": the one forbidden sentence here is the one that
    says it cannot help, because silence and confusion are what people quit over. It
    raises, and the turn goes to the model instead.
    """
    out = flat(v_queue(doc))
    if not out:
        raise ValueError("the waiting queue rendered nothing")
    return out if _SAYS_QUEUE.search(out) else WAITING_LEAD + out


def waiting_answer() -> str:
    """The live answer: `kb needs-you --json`, folded and rendered.

    READ FRESH, NOT OFF THE WARM SNAPSHOT. The snapshot exists so that a turn costs no
    subprocess, and this turn costs exactly one because the answer is the whole point:
    "what is waiting on me", read out of a document up to thirty idle seconds old, is the
    stale-fact-spoken-as-a-current-one this package refuses. One `kb` call is about a
    tenth of a second, which is well inside what the answer promises.
    """
    return render({"queue": snapshot.needs_you_rows()})
